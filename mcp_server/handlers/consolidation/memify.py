"""Memify cycle: self-improvement via pruning, strengthening, and reweighting.

Prunes low-quality memories, boosts important ones, and adjusts relationship
weights based on entity heat.

Returns include diagnostic ``reason_for_zero`` / ``reason_for_inaction``
fields when the cycle produces no mutation counters, distinguishing
early-return from a genuine "nothing to do" pass (issue #14 P2, darval).
"""

from __future__ import annotations

import logging

from mcp_server.core.curation import (
    compute_relationship_reweights,
    identify_prunable,
    identify_strengtheneable,
)
from mcp_server.handlers.consolidation.chunks import iter_memory_chunks
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.observability import silent_failure

logger = logging.getLogger(__name__)

# Thresholds mirror the defaults applied inside
# `identify_prunable` / `identify_strengtheneable`. Pulled to module
# scope so the diagnostic reclassification can reproduce the same
# gates without calling back into the curation helpers.
# Source: mcp_server.core.curation (identify_prunable defaults).
_PRUNE_HEAT_THRESHOLD = 0.01
_PRUNE_CONFIDENCE_THRESHOLD = 0.3
_STRENGTHEN_MIN_ACCESS = 5
_STRENGTHEN_MIN_CONFIDENCE = 0.8

# Heat below which the diagnostic `heat_lt05` flag counts a memory as cool.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_LOW_HEAT_THRESHOLD = 0.5


def run_memify_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Run memify self-improvement: prune, strengthen, reweight.

    `memories` may be pre-loaded by the consolidate handler (issue #13).

    Postcondition (issue #14 P2):
      * Always returns ``pruned``, ``strengthened``, ``reweighted``.
      * When all three counters are zero → additive
        ``reason_for_zero`` key with one of ``passed_through``,
        ``below_access_threshold``, ``below_stale_threshold``,
        ``reweight_only_gate``.
      * When ``pruned == 0 AND strengthened == 0 AND reweighted > 0`` →
        additive ``reason_for_inaction`` key with one of the same
        values. ``pruned`` / ``strengthened`` / ``reweighted`` are
        preserved unchanged.
      * When any of ``pruned`` / ``strengthened`` is non-zero → both
        diagnostic keys are absent.
    """
    pruned, strengthened, flags, scanned = _stream_prune_strengthen(store, memories)
    reweighted = _reweight_relationships(store)

    stats: dict[str, int | str] = {
        "pruned": pruned,
        "strengthened": strengthened,
        "reweighted": reweighted,
    }

    reason = _classify_memify_reason(pruned, strengthened, reweighted, scanned, flags)
    if reason is not None:
        if pruned == 0 and strengthened == 0 and reweighted == 0:
            stats["reason_for_zero"] = reason
        elif pruned == 0 and strengthened == 0 and reweighted > 0:
            stats["reason_for_inaction"] = reason
        _log_if_passed_through("memify", stats, scanned=scanned)

    return stats


def _accumulate_memify_flags(flags: dict[str, bool], mem: dict) -> None:
    """Fold one memory into the diagnostic candidate-presence flags.

    Replaces the post-hoc ``any(...)`` scans over the full list with a single
    streaming accumulation, so classification needs no resident corpus.
    """
    heat = mem.get("heat", 1.0)
    if heat < _PRUNE_HEAT_THRESHOLD and mem.get("confidence", 1.0) < (
        _PRUNE_CONFIDENCE_THRESHOLD
    ):
        flags["prune_cand"] = True
    access = mem.get("access_count", 0)
    if access >= _STRENGTHEN_MIN_ACCESS and mem.get("confidence", 0) >= (
        _STRENGTHEN_MIN_CONFIDENCE
    ):
        flags["strengthen_cand"] = True
    if access > 0:
        flags["access_gt0"] = True
    if heat < _LOW_HEAT_THRESHOLD:
        flags["heat_lt05"] = True


def _stream_prune_strengthen(
    store: MemoryStore, memories: list[dict] | None
) -> tuple[int, int, dict[str, bool], int]:
    """Stream prune + strengthen + diagnostic flags in ONE pass.

    ``identify_prunable`` / ``identify_strengtheneable`` are per-memory
    threshold filters, so applying them per chunk and unioning the effects is
    equivalent to one full-list call — at O(chunk) RAM instead of O(N). Deletes
    / importance updates go through the interactive pool, so they don't contend
    with the batch-pool read cursor, and the cursor's MVCC snapshot keeps the
    scan stable across the deletes. Returns (pruned, strengthened, flags,
    scanned).
    """
    pruned = strengthened = scanned = 0
    flags = {
        "prune_cand": False,
        "strengthen_cand": False,
        "access_gt0": False,
        "heat_lt05": False,
    }
    for chunk in iter_memory_chunks(store, memories):
        for mem in chunk:
            scanned += 1
            _accumulate_memify_flags(flags, mem)
        for mid in identify_prunable(chunk):
            try:
                store.delete_memory(mid)
                pruned += 1
            except Exception as exc:  # noqa: BLE001 — per-memory failure must not abort the pass
                silent_failure.note("consolidation.memify_prune", exc)
        for mid, new_importance in identify_strengtheneable(chunk):
            try:
                store.update_memory_importance(mid, new_importance)
                strengthened += 1
            except Exception as exc:  # noqa: BLE001 — per-memory failure must not abort the pass
                silent_failure.note("consolidation.memify_strengthen", exc)
    return pruned, strengthened, flags, scanned


def _classify_memify_reason(
    pruned: int,
    strengthened: int,
    reweighted: int,
    scanned: int,
    flags: dict[str, bool],
) -> str | None:
    """Classify the early-return path for memify (from streamed flags).

    Same decision table as before, but driven by the streaming-accumulated
    candidate-presence flags and the scanned count rather than a resident list:

      * ``below_stale_threshold`` — memories exist but none are cold /
        low-confidence enough to prune.
      * ``below_access_threshold`` — none crossed the strengthen access gate.
      * ``reweight_only_gate`` — nothing crossed prune/strengthen, yet reweight
        fired (only in the ``reweighted > 0`` "inaction" shape).
      * ``passed_through`` — genuine quiet-store no-op.
    """
    if (pruned != 0) or (strengthened != 0):
        return None

    all_zero = (pruned == 0) and (strengthened == 0) and (reweighted == 0)
    inaction = (pruned == 0) and (strengthened == 0) and (reweighted > 0)
    if not (all_zero or inaction):
        return None

    if scanned == 0:
        return "passed_through"

    has_prune_candidates = flags["prune_cand"]
    has_strengthen_candidates = flags["strengthen_cand"]

    if inaction and not has_prune_candidates and not has_strengthen_candidates:
        return "reweight_only_gate"
    if has_prune_candidates or has_strengthen_candidates:
        return "passed_through"
    if not has_strengthen_candidates and flags["access_gt0"]:
        return "below_access_threshold"
    if not has_prune_candidates and flags["heat_lt05"]:
        return "below_stale_threshold"

    return "passed_through"


def _log_if_passed_through(
    stage_name: str,
    stats: dict,
    scanned: int,
) -> None:
    """Emit an INFO log when the stage finished as a genuine no-op.

    Issue #14 P2 (darval): operators grep
    ``stage=<name> reason=passed_through`` to distinguish "quiet store"
    runs from early-return runs. Only fires when the classified reason
    is ``passed_through`` on either field (``reason_for_zero`` or
    ``reason_for_inaction``). Duration is tracked by the outer ``_timed``
    wrapper; we pass 0 here because the handler sees the stage before
    ``duration_ms`` is injected.
    """
    reason = stats.get("reason_for_zero") or stats.get("reason_for_inaction")
    if reason != "passed_through":
        return
    logger.info(
        "stage=%s reason=passed_through scanned=%d duration_ms=%d",
        stage_name,
        scanned,
        0,
    )


def _reweight_relationships(store: MemoryStore) -> int:
    """Adjust relationship weights based on entity heat.

    Phase 5: runs on the batch pool (long-running consolidation stage).
    """
    try:
        entities = store.get_all_entities(min_heat=0.0)
        entity_heats = {e["id"]: e.get("heat", 0.5) for e in entities}

        with store.acquire_batch() as conn:
            rows = conn.execute(
                "SELECT id, source_entity_id, target_entity_id, weight "
                "FROM relationships",
            ).fetchall()
            rels = [dict(r) for r in rows]
            reweights = compute_relationship_reweights(rels, entity_heats)

            count = 0
            for rid, new_weight in reweights:
                conn.execute(
                    "UPDATE relationships SET weight = %s WHERE id = %s",
                    (new_weight, rid),
                )
                count += 1
        return count
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is observable via silent_failure
        silent_failure.note("memify.relationship_reweight", exc)
        return 0
