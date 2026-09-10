"""Homeostatic cycle: per-write-class health measurement + regulation.

**A3 lazy-heat implementation**: heat is a *function*, not a *state vector*.
The multiplicative scaling factor is stored as a single scalar per
(domain, write_class) in ``homeostatic_state.factor`` and read by
``effective_heat()`` at query time:

    effective_heat(m, t, factor) = LEAST(1.0, GREATEST(floor,
        heat_base * factor * POWER(decay_factor, α·t)))

source: ADR-0362"""

from __future__ import annotations

import logging

from mcp_server.core import homeostatic_health
from mcp_server.handlers.consolidation import homeostatic_apply
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.shared import write_class

logger = logging.getLogger(__name__)

_TARGET_HEAT = homeostatic_apply.TARGET_HEAT
_BIMODALITY_TRIGGER = homeostatic_apply.BIMODALITY_TRIGGER

# source: ADR-0057
_REGULATED_CLASSES = frozenset({write_class.AUTO})


def run_homeostatic_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Measure health and (for regulated classes) update the homeostatic
        factor / fold, independently per write class.

        Returns:
            Same top-level shape as before stratification
            (scaling_applied/scaling_kind/health_score/mean_heat/std_heat/
            bimodality/memories_scanned) mirroring the ``auto`` class's
            outcome — existing callers that only look at the top level see
            identical behavior to pre-M-D3 for the auto-dominated corpus.
            Additive key ``by_class``: ``{class_name: outcome_dict}`` for
            every class in ``write_class.ALL_WRITE_CLASSES``.

    source: ADR-0362"""
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

    source: ADR-0362"""
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]
