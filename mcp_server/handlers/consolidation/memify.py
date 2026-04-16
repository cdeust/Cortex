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
from mcp_server.infrastructure.memory_store import MemoryStore

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
    if memories is None:
        memories = store.get_all_memories_for_decay()

    pruned = _prune_memories(store, memories)
    strengthened = _strengthen_memories(store, memories)
    reweighted = _reweight_relationships(store)

    stats = {
        "pruned": pruned,
        "strengthened": strengthened,
        "reweighted": reweighted,
    }

    reason = _classify_memify_reason(pruned, strengthened, reweighted, memories)
    if reason is not None:
        if pruned == 0 and strengthened == 0 and reweighted == 0:
            stats["reason_for_zero"] = reason
        elif pruned == 0 and strengthened == 0 and reweighted > 0:
            stats["reason_for_inaction"] = reason
        _log_if_passed_through("memify", stats, scanned=len(memories))

    return stats


def _classify_memify_reason(
    pruned: int,
    strengthened: int,
    reweighted: int,
    memories: list[dict],
) -> str | None:
    """Classify the early-return path for memify.

    Precondition: counters reflect the actual cycle outcome.
    Postcondition: returns None unless (a) all three counters are zero,
    or (b) ``pruned == 0 AND strengthened == 0 AND reweighted > 0``.
    Otherwise returns one of:

      * ``below_stale_threshold`` — candidate memories exist but none
        are cold / low-confidence / zero-access enough to prune.
      * ``below_access_threshold`` — candidates exist but none have
        crossed the strengthen access-count gate.
      * ``reweight_only_gate`` — intentional gating: nothing crossed
        either the prune or the strengthen thresholds, yet the
        relationship reweight step did fire. Used only when
        ``reweighted > 0`` (the "inaction" shape).
      * ``passed_through`` — candidates exist that would cross at
        least one gate if the thresholds matched them, AND the
        candidates did not materialise. True quiet-store no-op.

    Priority: when all counters are zero and memories is empty →
    ``passed_through`` (nothing to inspect). Else: prefer the tightest
    gate that rejected candidates.
    """
    action_nonzero = (pruned != 0) or (strengthened != 0)
    if action_nonzero:
        return None

    all_zero = (pruned == 0) and (strengthened == 0) and (reweighted == 0)
    inaction = (pruned == 0) and (strengthened == 0) and (reweighted > 0)
    if not (all_zero or inaction):
        return None

    if not memories:
        return "passed_through"

    # Inspect which gate rejected candidates that were present.
    has_prune_candidates = any(
        m.get("heat", 1.0) < _PRUNE_HEAT_THRESHOLD
        and m.get("confidence", 1.0) < _PRUNE_CONFIDENCE_THRESHOLD
        for m in memories
    )
    has_strengthen_candidates = any(
        m.get("access_count", 0) >= _STRENGTHEN_MIN_ACCESS
        and m.get("confidence", 0) >= _STRENGTHEN_MIN_CONFIDENCE
        for m in memories
    )

    # Reweight happened but no prune/strengthen → intentional gating.
    if inaction and not has_prune_candidates and not has_strengthen_candidates:
        return "reweight_only_gate"

    # All three zero: identify which threshold is missing signal.
    if has_prune_candidates or has_strengthen_candidates:
        return "passed_through"
    if not has_strengthen_candidates and any(
        m.get("access_count", 0) > 0 for m in memories
    ):
        return "below_access_threshold"
    if not has_prune_candidates and any(m.get("heat", 1.0) < 0.5 for m in memories):
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


def _prune_memories(store: MemoryStore, memories: list[dict]) -> int:
    """Delete prunable low-quality memories."""
    prunable_ids = identify_prunable(memories)
    count = 0
    for mid in prunable_ids:
        try:
            store.delete_memory(mid)
            count += 1
        except Exception:
            pass
    return count


def _strengthen_memories(store: MemoryStore, memories: list[dict]) -> int:
    """Boost importance of memories that deserve strengthening."""
    strengthen_list = identify_strengtheneable(memories)
    count = 0
    for mid, new_importance in strengthen_list:
        try:
            store.update_memory_importance(mid, new_importance)
            count += 1
        except Exception:
            pass
    return count


def _reweight_relationships(store: MemoryStore) -> int:
    """Adjust relationship weights based on entity heat."""
    try:
        entities = store.get_all_entities(min_heat=0.0)
        entity_heats = {e["id"]: e.get("heat", 0.5) for e in entities}

        rows = store._conn.execute(
            "SELECT id, source_entity_id, target_entity_id, weight FROM relationships",
        ).fetchall()
        rels = [dict(r) for r in rows]
        reweights = compute_relationship_reweights(rels, entity_heats)

        count = 0
        for rid, new_weight in reweights:
            store._conn.execute(
                "UPDATE relationships SET weight = %s WHERE id = %s",
                (new_weight, rid),
            )
            count += 1
        if count:
            store._conn.commit()
        return count
    except Exception:
        return 0
