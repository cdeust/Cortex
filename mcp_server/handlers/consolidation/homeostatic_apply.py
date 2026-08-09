"""Homeostatic regulation mechanics: scalar update, fold, bimodal cohort.

Split from ``homeostatic.py`` to keep both files under the 500-line cap
(§4.1 coding standards) — same precedent as ``core/homeostatic_health.py``
("Split from homeostatic_plasticity.py to keep files under 300 lines").
``homeostatic.py`` owns the policy (which write class gets regulated, and
why — ``_REGULATED_CLASSES``); this module owns the mechanics (how a
single, already-class-scoped population gets scaled/folded/cohort-
corrected). ``homeostatic.py::_dispatch_class`` is the only caller.

References:
    Turrigiano 2008 — multiplicative synaptic scaling (order-preserving)
    Tetzlaff 2011 Eq. 3 — delta_w = alpha * w * (r_target - r_actual)
    Pfister 2013 — bimodality coefficient
    docs/program/phase-3-a3-migration-design.md §5
    scratchpad/memoire-qui-comprend-design.md §M-D3
"""

from __future__ import annotations

import logging
import math

from mcp_server.core import homeostatic_health, homeostatic_plasticity
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.shared import write_class

logger = logging.getLogger(__name__)

# source: Pfister et al. (2013) "Good things peak in pairs." Frontiers in
#         Psychology 4:700 — b > 5/9 ≈ 0.555 is the formal criterion. But
#         uniform distributions also sit at ~0.555 (denominator =
#         kurtosis_excess + 3, kurtosis_excess ≈ -1.2 for uniform → b ≈
#         1/1.8 ≈ 0.556), so the Pfister threshold false-positives on
#         platykurtic unimodal data. Cortex uses 0.7 for a clean margin:
#         true bimodal distributions score > 1.0 (measured); uniform/
#         unimodal score < 0.6 (measured). Empirically calibrated on
#         synthetic fixtures.
BIMODALITY_TRIGGER = 0.7

# Homeostatic target mean (Turrigiano 2008).
TARGET_HEAT = 0.4

# Fold trigger: when |log(factor)| > log(2.0), the scalar has drifted
# into prefilter-distorting territory.
_FOLD_LOG_THRESHOLD = math.log(2.0)

# Minimum mean-effective-heat before the scaling divisor is numerically
# safe. Below this we skip the cycle rather than amplify noise.
_MIN_SAFE_MEAN = 0.01

# Per-cycle cap on the multiplicative step relative to the current factor.
# Matches the legacy Turrigiano α=0.05 ceiling (~3% per cycle).
_MAX_STEP = 0.03

# Health score at or above which (absent bimodality) no rescaling runs.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_HEALTHY_SCORE_MIN = 0.6

# Minimum per-row heat change worth a write; smaller deltas are noise.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_HEAT_WRITE_EPSILON = 0.001


def dispatch(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    health: dict,
    domain: str | None = None,
    cls: str = write_class.AUTO,
) -> dict:
    """Pick the right primitive given distribution health, for one
    (already class-scoped) population.

    ``domain`` is the dominant-domain key within ``cls``'s own rows,
    pre-resolved by the caller (``homeostatic._dispatch_class``) from an
    exact frequency count; defaults to ``None`` (resolved from
    ``memories`` by ``apply_scalar``) so direct unit-test call sites that
    predate M-D3 keep working unchanged. ``cls`` is threaded through to
    ``apply_scalar``/``_apply_fold`` so the fold's UPDATE and the factor
    row it writes stay scoped to this class; defaults to ``AUTO`` — the
    only class this is ever called for in production.
    """
    bimodality = health["bimodality_coefficient"]
    mean = health["mean"]
    std = health["std"]

    if (
        health["health_score"] >= _HEALTHY_SCORE_MIN
        and bimodality <= BIMODALITY_TRIGGER
    ):
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            # Scale-invariant branch: no writes → shape unchanged.
            "bimodality_after": bimodality,
        }

    if bimodality > BIMODALITY_TRIGGER:
        return apply_cohort(store, memories, heats, mean, std, bimodality)

    return apply_scalar(store, memories, mean, bimodality, domain, cls)


# ── Scalar + fold ────────────────────────────────────────────────────────


def apply_scalar(
    store: MemoryStore,
    memories: list[dict],
    mean: float,
    bimodality: float,
    domain: str | None = None,
    cls: str = write_class.AUTO,
) -> dict:
    """One UPDATE on homeostatic_state.factor + optional fold, scoped to
    ``(domain, cls)``.

    Replaces the legacy N-row Turrigiano UPDATE with one scalar write.
    Fold (factor ∉ [0.5, 2.0]) writes heat_base per-row (restricted to
    ``cls``'s own source values) and resets factor=1.0 — expected
    ~once/month per (domain, class).

    ``domain``: pre-resolved dominant-domain key within ``cls``. When
    ``None``, resolved here from ``memories`` (unit-test call sites that
    exercise this function directly without going through ``dispatch``).
    ``cls``: defaults to ``AUTO`` — the only class this function is ever
    called for in production (``homeostatic._REGULATED_CLASSES``); the
    default keeps direct unit-test call sites unchanged.
    """
    if mean <= _MIN_SAFE_MEAN:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": bimodality,
            "reason_for_zero": "mean_below_safety_floor",
        }

    if domain is None:
        domain = _dominant_domain(memories)
    factor_old = _safe_get_factor(store, domain, cls)
    factor_new = factor_old * (TARGET_HEAT / mean)
    factor_new = _clamp_step(factor_old, factor_new, max_step=_MAX_STEP)

    if abs(factor_new - factor_old) <= 0.005 * max(factor_old, 1e-6):
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": bimodality,
            "reason_for_zero": "factor_stable",
            "factor": round(factor_old, 4),
        }

    # scalar_update: heat_base is NOT rewritten — only homeostatic_state.factor
    # changes. Stored-heat distribution is literally identical → bimodality
    # coefficient is unchanged. fold: heat_base IS rewritten per-row with
    # [0.0, 1.0] clipping; when many rows saturate the shape can shift, so
    # on fold we report the pre-fold value as a bounded estimate and flag
    # that the post-fold value would require a re-scan to compute exactly.
    # See issue #14 OB4 — null was previously ambiguous.

    if _fold_triggered(factor_new):
        folded = _apply_fold(store, domain, factor_new, cls)
        return {
            "scaling_applied": True,
            "scaling_kind": "fold",
            "bimodality_before": bimodality,
            # fold clips heats at 0/1 — shape can shift slightly when many
            # rows saturate. We do NOT re-scan post-fold (would cost another
            # 66 k row scan at steady state); the returned value is the
            # pre-fold shape, treated as a bounded estimate. Next consolidate
            # will measure exactly.
            "bimodality_after": bimodality,
            "bimodality_after_is_estimate": True,
            "factor_pre_fold": round(factor_new, 4),
            "rows_folded": folded,
        }

    store.set_homeostatic_factor(domain, factor_new, write_class=cls)
    return {
        "scaling_applied": True,
        "scaling_kind": "scalar_update",
        "bimodality_before": bimodality,
        "bimodality_after": bimodality,
        "factor": round(factor_new, 4),
        "factor_delta": round(factor_new - factor_old, 4),
    }


def _fold_triggered(factor: float) -> bool:
    """Fold when |log(factor)| > log(2.0) — factor ∉ [0.5, 2.0]."""
    if factor <= 0.0:
        return False
    return abs(math.log(factor)) > _FOLD_LOG_THRESHOLD


def _apply_fold(store: MemoryStore, domain: str, factor: float, cls: str) -> int:
    """Multiply heat_base by factor for class ``cls``'s own rows, reset
    homeostatic_state.factor=1.0 for ``(domain, cls)``.

    Writes are bounded by the domain partition AND ``memories.write_class
    = cls`` directly (7.4: the explicit column landed in the same
    migration this predicate switch ships with — no second classification
    path, per ``mcp_server.shared.write_class``'s module doctrine). Pre-7.4
    rows read the column's DEFAULT (``'deliberate'``, the safe default —
    see ``infrastructure/pg_schema.py``'s MIGRATIONS_DDL comment) until
    the one-shot backfill (``handlers/consolidation/write_class_backfill.py``)
    reclassifies them from ``source``; until that backfill runs, true
    ``auto`` rows written before 7.4 are conservatively EXCLUDED from
    folding (a delayed correction, self-heals on the next fold cycle after
    backfill — never the opposite, irreversible failure mode of folding
    deliberate content, which is the regression this whole design fixes).
    Skips protected/no_decay/stale. Amortized once per month per (domain,
    class) under normal operation. Phase 5: batched UPDATE runs on the
    batch pool. Journals the event (M-D3 telemetry step 1 — the
    2026-07-10 19:22 fold left no queryable trace anywhere but row
    timestamps; every fold from here forward is DB-queryable).
    """
    if cls not in write_class.ALL_WRITE_CLASSES:
        logger.warning(
            "Homeostatic fold requested for unknown write class %r — refusing.",
            cls,
        )
        return 0
    with store.acquire_batch() as conn:
        result = conn.execute(
            "UPDATE memories "
            "SET heat_base = LEAST(1.0, GREATEST(0.0, heat_base * %s)), "
            "    heat_base_set_at = NOW() "
            "WHERE domain = %s "
            "  AND write_class = %s "
            "  AND NOT is_protected "
            "  AND NOT no_decay "
            "  AND NOT is_stale",
            (float(factor), domain or "", cls),
        )
        rows = int(getattr(result, "rowcount", 0) or 0)
    store.set_homeostatic_factor(domain, 1.0, write_class=cls)
    try:
        store.log_homeostatic_fold(domain, cls, factor, rows)
    except AttributeError:
        # Test doubles / stores predating M-D3 may not implement the
        # journal method — the fold itself must not fail because of it.
        pass
    return rows


def _dominant_domain(memories: list[dict]) -> str:
    """Pick the most-frequent domain as the scaling key (materialized rows)."""
    counts: dict[str, int] = {}
    for mem in memories:
        d = mem.get("domain") or ""
        counts[d] = counts.get(d, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _safe_get_factor(store: MemoryStore, domain: str, cls: str) -> float:
    try:
        return float(store.get_homeostatic_factor(domain, write_class=cls))
    except TypeError:
        # Test doubles predating M-D3 (positional-only get_homeostatic_
        # factor(domain)) — fall back to the pre-stratification call
        # shape rather than fail the cycle.
        try:
            return float(store.get_homeostatic_factor(domain))
        except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.debug("get_homeostatic_factor(%r) failed: %s", domain, exc)
            return 1.0
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("get_homeostatic_factor(%r, %r) failed: %s", domain, cls, exc)
        return 1.0


def _clamp_step(old: float, new: float, max_step: float) -> float:
    """Cap the per-cycle multiplicative step at ±max_step relative to old."""
    if old <= 0.0:
        return new
    ratio = new / old
    ratio = max(1.0 - max_step, min(1.0 + max_step, ratio))
    return old * ratio


# ── Bimodal cohort path ──────────────────────────────────────────────────


def apply_cohort(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    mean: float,
    std: float,
    bimodality: float,
) -> dict:
    """Bimodal path: pull the hot cohort toward TARGET_HEAT.

    Per-row writes route through ``bump_heat_raw`` (the I2 canonical
    writer). Subtraction is not meaningful on a scalar factor, so this
    branch writes heat_base directly. ``memories``/``heats`` are already
    scoped to one write class by the caller (``homeostatic._dispatch_
    class`` only invokes this for a regulated class's own thin-row list)
    — no additional class predicate is needed here, unlike the fold
    branch's raw SQL UPDATE.
    """
    cohort_idx = homeostatic_plasticity.detect_hot_cohort(heats, mean, std)
    if not cohort_idx:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            # Empty cohort → no writes → shape unchanged.
            "bimodality_after": bimodality,
            "reason_for_zero": "bimodal_but_no_cohort_detected",
        }
    scaled = homeostatic_plasticity.apply_cohort_correction(
        heats, cohort_idx, target_mean=TARGET_HEAT
    )
    after = homeostatic_health.compute_distribution_health(
        scaled, target_mean=TARGET_HEAT
    )

    # Darval O1 instrumentation: report per-row heat movement so
    # operators can see that cohort_correction DID pull rows down,
    # even when bimodality (a global shape metric) barely moves.
    # The bimodality metric is slow-converging; retrieval ranking cares
    # about per-row heat, which heat_delta_* measures directly.
    deltas_abs: list[float] = []
    writes = 0
    for i, new_heat in enumerate(scaled):
        delta = new_heat - heats[i]
        if abs(delta) > _HEAT_WRITE_EPSILON:
            store.bump_heat_raw(memories[i]["id"], round(new_heat, 4))
            writes += 1
        if i in set(cohort_idx):
            deltas_abs.append(abs(delta))
    mean_delta = sum(deltas_abs) / max(len(deltas_abs), 1)
    max_delta = max(deltas_abs) if deltas_abs else 0.0
    return {
        "scaling_applied": True,
        "scaling_kind": "cohort_correction",
        "bimodality_before": bimodality,
        "bimodality_after": after["bimodality_coefficient"],
        "cohort_size": len(cohort_idx),
        "cohort_mean_heat_delta": round(mean_delta, 4),
        "cohort_max_heat_delta": round(max_delta, 4),
        "cohort_rows_written": writes,
    }


def log_diagnostics_by_class(outcomes: dict[str, dict]) -> None:
    for cls, outcome in outcomes.items():
        if (
            outcome.get("scaling_kind") == "cohort_correction"
            and outcome.get("bimodality_after") is not None
            and outcome["bimodality_after"] >= outcome["bimodality_before"]
        ):
            logger.warning(
                "Cohort correction did not reduce bimodality (class=%s): "
                "before=%.3f after=%.3f cohort_size=%s",
                cls,
                outcome["bimodality_before"],
                outcome["bimodality_after"],
                outcome.get("cohort_size"),
            )
        if outcome.get("scaling_kind") == "fold":
            logger.info(
                "Homeostatic fold triggered (class=%s): factor_pre_fold=%.4f "
                "rows_folded=%d",
                cls,
                outcome.get("factor_pre_fold", 0.0),
                outcome.get("rows_folded", 0),
            )
