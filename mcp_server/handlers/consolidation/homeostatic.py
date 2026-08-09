"""Homeostatic cycle: per-write-class health measurement + regulation.

**A3 lazy-heat implementation**: heat is a *function*, not a *state vector*.
The multiplicative scaling factor is stored as a single scalar per
(domain, write_class) in ``homeostatic_state.factor`` and read by
``effective_heat()`` at query time:

    effective_heat(m, t, factor) = LEAST(1.0, GREATEST(floor,
        heat_base * factor * POWER(decay_factor, α·t)))

**M-D3 (7.1, 2026-07-10) — full stratification by write class.** Design
doc ``scratchpad/memoire-qui-comprend-design.md`` §M-D3, arbitrage user:
"stratification complète, pas l'exemption minimale". Confirmed empirically
(SQL against dev DB, before this change): the class-blind fold at
2026-07-10 19:22 wrote ``heat_base *= factor`` + reset
``heat_base_set_at`` on **1021 rows in one UPDATE**, 511 of them
``post_tool_capture`` (auto) and 510 of them deliberate-class sources
(feature/lesson/bug-fix/benchmark/decision/...) — the fold's target-mean
regulation was computed against the WHOLE domain's mean (92% auto by
volume, I6 audit) and then applied to every row in that domain including
the deliberate minority, collapsing the deliberate class's median
``heat_base`` from 0.25 (post re-heat campaign, 15:13Z) to 0.1346 hours
later. The re-heat campaign's own effect was erased same-day, not at the
planned J+30 check.

Every write class now gets its own health measurement AND its own fold
verdict — not one aggregate computation with an exclusion predicate
bolted onto it. See ``_REGULATED_CLASSES`` below for which classes are
actually SCALED (currently: only ``auto``) and why — every non-regulated
class's health is still measured and journaled, its fold verdict is just
always "none" by documented doctrine, not by omission.

This module owns the POLICY (which write class is measured/regulated,
how the corpus is bucketed per cycle). The MECHANICS (scalar update,
fold, bimodal cohort correction — the actual writes) live in
``homeostatic_apply.py`` — split to keep both files under the 500-line
cap (§4.1 coding standards), same precedent as
``core/homeostatic_health.py``.

References:
    Turrigiano 2008 — multiplicative synaptic scaling (order-preserving)
    Tetzlaff 2011 Eq. 3 — delta_w = alpha * w * (r_target - r_actual)
    docs/program/phase-3-a3-migration-design.md §5
    scratchpad/memoire-qui-comprend-design.md §M-D2, §M-D3
"""

from __future__ import annotations

import logging

from mcp_server.core import homeostatic_health
from mcp_server.handlers.consolidation import homeostatic_apply
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.shared import write_class

logger = logging.getLogger(__name__)

_TARGET_HEAT = homeostatic_apply.TARGET_HEAT
_BIMODALITY_TRIGGER = homeostatic_apply.BIMODALITY_TRIGGER

# M-D3 doctrine — which write classes are subject to target-mean
# regulation (scalar update, fold, AND cohort correction; all three are
# forms of the same mechanism: pulling a distribution toward
# _TARGET_HEAT). No new numeric constants invented (§8 coding standards)
# — this set is a class-membership decision, not a numeric one:
#
#   auto        REGULATED. This is the population the mechanism was
#               validated for (ROC-AUC / Turrigiano-Tetzlaff assumptions
#               both presume an ongoing, high-volume, statistically-
#               exchangeable population competing for one heat budget —
#               exactly the auto-capture flood, 92% of the corpus by
#               volume, I6 audit).
#   deliberate  NOT regulated. Individually-meaningful, low-volume
#               witnesses (~5-8% of writes, audit) — not exchangeable,
#               not flood-like. Regulating their mean toward the SAME
#               set-point as the flood is the exact mechanism that
#               re-suppressed the class this increment exists to fix
#               (module docstring above).
#   derived     NOT regulated. Near-empty today (0 rows, design-doc
#               audit) and structurally bursty/capped (memify_derive caps
#               20 attempts/run) — Welford moments on tiny N are
#               statistically unstable, and duplication is already
#               judged by the ``derived-rel:`` idempotence marker rather
#               than a heat threshold (M-D2's "derived" write-gate row
#               makes the same argument; regulation would measure the
#               same wrong quantity here).
#   mechanical  NOT regulated. One-shot bulk-import passes (backfill,
#               seed, ingest, codebase scan) — not an ongoing rate. The
#               "target firing rate" doctrine (Turrigiano 2008, Tetzlaff
#               2011) has no referent for a single injection event; there
#               is no runaway to defend against.
_REGULATED_CLASSES = frozenset({write_class.AUTO})


def run_homeostatic_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Measure health and (for regulated classes) update the homeostatic
    factor / fold, independently per write class.

    Branching (per class, in ``_dispatch_class``):
      1. class not regulated → verdict is always "none", health still
         measured and reported (M-D3 doctrine, see ``_REGULATED_CLASSES``).
      2. healthy AND unimodal → no-op.
      3. bimodal → cohort correction (per-row writes via bump_heat_raw),
         scoped to that class's own rows.
      4. off-target → scalar factor update, fold if drift > log(2.0),
         scoped to that class's own rows.

    Phase 4: when the caller passes ``memories=None`` we compute the
    health metrics via a streaming server-side cursor
    (``store.iter_memories_for_decay``) + per-class Welford moments. Peak
    memory is O(chunk_size) instead of O(N) — crucial at 66K+ memory
    stores. When the caller passes a pre-loaded list (hot-path consolidate
    sharing one snapshot across stages, or unit tests), we bucket it by
    class directly.

    Returns:
        Same top-level shape as before stratification
        (scaling_applied/scaling_kind/health_score/mean_heat/std_heat/
        bimodality/memories_scanned) mirroring the ``auto`` class's
        outcome — existing callers that only look at the top level see
        identical behavior to pre-M-D3 for the auto-dominated corpus.
        Additive key ``by_class``: ``{class_name: outcome_dict}`` for
        every class in ``write_class.ALL_WRITE_CLASSES``.
    """
    try:
        if memories is None:
            class_health, class_domain_counts, class_thin, total = (
                _streaming_health_by_class(store)
            )
        else:
            if not memories:
                return _empty_cycle_result()
            class_health, class_domain_counts, class_thin, total = (
                _bucket_materialized_by_class(memories)
            )

        if total == 0:
            return _empty_cycle_result()

        outcomes: dict[str, dict] = {}
        for cls in write_class.ALL_WRITE_CLASSES:
            outcomes[cls] = _dispatch_class(
                store,
                cls,
                class_health.get(cls, (_empty_health(), 0)),
                class_domain_counts.get(cls, {}),
                class_thin.get(cls, []),
            )

        homeostatic_apply.log_diagnostics_by_class(outcomes)

        auto_outcome = outcomes[write_class.AUTO]
        return {
            **auto_outcome,
            "by_class": outcomes,
            "memories_scanned": total,
        }
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("Homeostatic cycle failed: %s", exc, exc_info=True)
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "health_score": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _empty_health() -> dict:
    """Public-API empty-health dict (no private-member access across the
    module boundary) — ``compute_distribution_health([])`` returns the
    same shape ``compute_distribution_health_streaming_by_class`` uses
    for a class with zero observations."""
    return homeostatic_health.compute_distribution_health([], target_mean=_TARGET_HEAT)


def _empty_cycle_result() -> dict:
    return {
        "scaling_applied": False,
        "scaling_kind": "none",
        "health_score": None,
        "reason": "no_memories",
        "memories_scanned": 0,
    }


def _dispatch_class(
    store: MemoryStore,
    cls: str,
    health_and_count: tuple[dict, int],
    domain_counts: dict[str, int],
    thin_memories: list[dict],
) -> dict:
    """Resolve one write class's outcome: measured always, regulated
    (scaled/folded/cohort-corrected) only if ``cls in _REGULATED_CLASSES``.
    """
    health, n = health_and_count
    if n == 0:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "health_score": None,
            "reason": "no_memories",
            "memories_scanned": 0,
        }

    base = {
        "health_score": health["health_score"],
        "mean_heat": health["mean"],
        "std_heat": health["std"],
        "bimodality": health["bimodality_coefficient"],
        "memories_scanned": n,
    }

    if cls not in _REGULATED_CLASSES:
        return {
            **base,
            "scaling_applied": False,
            "scaling_kind": "none",
            "reason_for_zero": "class_not_regulated",
        }

    heats = [m.get("heat", 0.5) for m in thin_memories]
    domain = _pick_dominant_domain(domain_counts)
    outcome = homeostatic_apply.dispatch(
        store, thin_memories, heats, health, domain, cls
    )
    return {**base, **outcome}


# ── Per-class health accumulation ──────────────────────────────────────


def _slim_row(m: dict) -> dict:
    """Project a memory row to the fields dispatch actually reads."""
    return {
        "id": m.get("id"),
        "heat": m.get("heat", 0.5),
        "domain": m.get("domain", ""),
    }


def _streaming_health_by_class(
    store: MemoryStore,
) -> tuple[
    dict[str, tuple[dict, int]], dict[str, dict[str, int]], dict[str, list[dict]], int
]:
    """Per-class health via server-side cursor, one bounded pass.

    Buckets each streamed row into its write class (``classify_write_
    class``) while accumulating that class's (domain -> count) map and
    heat list, in the SAME cursor pass as before Phase-4-streaming's
    single global accumulation — O(distinct domain × class) memory, not
    O(N). Thin (id/heat/domain) rows are materialized in a SECOND,
    targeted pass — only for a regulated class whose bimodality triggers
    the cohort branch — mirroring the pre-stratification strategy of
    ``_slim_memories_for_dispatch`` (materialize only when a per-row
    write is actually about to happen).

    Returns:
        (class_health, class_domain_counts, class_thin_memories, total).
    """
    class_domain_counts: dict[str, dict[str, int]] = {
        c: {} for c in write_class.ALL_WRITE_CLASSES
    }
    total = 0

    def _accumulate(chunk: list[dict]) -> dict[str, list[float]]:
        nonlocal total
        buckets: dict[str, list[float]] = {}
        for m in chunk:
            total += 1
            cls = write_class.classify_write_class(m)
            d = m.get("domain") or ""
            class_domain_counts[cls][d] = class_domain_counts[cls].get(d, 0) + 1
            buckets.setdefault(cls, []).append(m.get("heat", 0.5))
        return buckets

    if not hasattr(store, "iter_memories_for_decay"):
        chunks = [_accumulate(store.get_all_memories_for_decay())]
    else:
        chunks = (_accumulate(chunk) for chunk in store.iter_memories_for_decay())

    class_health = homeostatic_health.compute_distribution_health_streaming_by_class(
        chunks, target_mean=_TARGET_HEAT, classes=write_class.ALL_WRITE_CLASSES
    )

    class_thin: dict[str, list[dict]] = {}
    for cls in _REGULATED_CLASSES:
        health, n = class_health.get(cls, ({}, 0))
        if n and health.get("bimodality_coefficient", 0.0) > _BIMODALITY_TRIGGER:
            class_thin[cls] = _slim_memories_for_class(store, cls)

    return class_health, class_domain_counts, class_thin, total


def _slim_memories_for_class(store: MemoryStore, cls: str) -> list[dict]:
    """(id, heat, domain) projection of active memories in write class
    ``cls`` — second targeted pass, only invoked when that class's
    bimodality triggers the cohort branch."""
    if not hasattr(store, "iter_memories_for_decay"):
        return [
            _slim_row(m)
            for m in store.get_all_memories_for_decay()
            if write_class.classify_write_class(m) == cls
        ]
    return [
        _slim_row(m)
        for chunk in store.iter_memories_for_decay()
        for m in chunk
        if write_class.classify_write_class(m) == cls
    ]


def _bucket_materialized_by_class(
    memories: list[dict],
) -> tuple[
    dict[str, tuple[dict, int]], dict[str, dict[str, int]], dict[str, list[dict]], int
]:
    """Bucket a pre-loaded memory list by write class (materializing /
    unit-test path — the list is already fully in memory)."""
    class_domain_counts: dict[str, dict[str, int]] = {
        c: {} for c in write_class.ALL_WRITE_CLASSES
    }
    class_heats: dict[str, list[float]] = {c: [] for c in write_class.ALL_WRITE_CLASSES}
    class_thin: dict[str, list[dict]] = {c: [] for c in write_class.ALL_WRITE_CLASSES}

    for m in memories:
        cls = write_class.classify_write_class(m)
        d = m.get("domain") or ""
        class_domain_counts[cls][d] = class_domain_counts[cls].get(d, 0) + 1
        class_heats[cls].append(m.get("heat", 0.5))
        class_thin[cls].append(_slim_row(m))

    class_health = {
        c: (
            homeostatic_health.compute_distribution_health(
                class_heats[c], target_mean=_TARGET_HEAT
            ),
            len(class_heats[c]),
        )
        for c in write_class.ALL_WRITE_CLASSES
    }
    return class_health, class_domain_counts, class_thin, len(memories)


def _pick_dominant_domain(counts: dict[str, int]) -> str:
    """Pick the most-frequent domain key from a precomputed frequency map.

    Same doctrine as before Phase 4: docs/program/phase-3-a3-migration-
    design.md §5 describes one scalar UPDATE per cycle, keyed by domain —
    M-D3 narrows this further to "one scalar UPDATE per (domain, class)
    per cycle, keyed within that class's own rows" — not a new weighting
    scheme, just the same rule applied within a class instead of across
    the whole corpus.
    """
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]
