"""Homeostatic cycle: scalar factor + fold.

**A3 lazy-heat implementation**: heat is a *function*, not a *state vector*.
The multiplicative scaling factor is stored as a single scalar per domain
in ``homeostatic_state.factor`` and read by ``effective_heat()`` at query
time:

    effective_heat(m, t, factor) = LEAST(1.0, GREATEST(floor,
        heat_base * factor * POWER(decay_factor, α·t)))

One row written per cycle instead of 66K.

**Fold trigger** (pre-filter fidelity): ``recall_memories()`` filters
``heat_base >= min_heat / factor``. If ``factor`` drifts far from 1.0,
this prefilter either admits too much (factor small) or cuts too much
(factor large). When ``|log(factor)| > log(2.0)`` — i.e., factor
∉ [0.5, 2.0] — we fold the scalar back into heat_base per-row (one
batched UPDATE) and reset factor=1.0. Fold is amortized: expected once
per month per domain under normal operation.

**Bimodal branch**: subtractive cohort correction still needs per-row
writes because subtraction on a scalar factor is not meaningful. The
cohort UPDATE routes through ``bump_heat_raw`` (the I2 canonical writer)
so bimodal handling preserves the single-writer invariant.

References:
    Turrigiano 2008 — multiplicative synaptic scaling (order-preserving)
    Tetzlaff 2011 Eq. 3 — delta_w = alpha * w * (r_target - r_actual)
    Pfister 2013 — bimodality coefficient
    Hinton & Salakhutdinov 2006 — subtractive renormalization
    docs/program/phase-3-a3-migration-design.md §5
"""

from __future__ import annotations

import logging
import math

from mcp_server.core import homeostatic_health, homeostatic_plasticity
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# Bimodality threshold above which multiplicative scaling is ineffective
# and subtractive cohort correction is applied instead.
# source: Pfister et al. (2013) "Good things peak in pairs." Frontiers in
#         Psychology 4:700 — b > 5/9 ≈ 0.555 is the formal criterion. But
#         uniform distributions also sit at ~0.555 because the formula is
#         sensitive to low kurtosis (denominator = kurtosis_excess + 3,
#         kurtosis_excess ≈ -1.2 for uniform → b ≈ 1/1.8 ≈ 0.556), so the
#         Pfister threshold has false-positives on platykurtic unimodal
#         data. Cortex uses 0.7 to give a clean margin: true bimodal
#         distributions score > 1.0 (measured); uniform/unimodal score
#         < 0.6 (measured). Empirically calibrated on synthetic fixtures.
_BIMODALITY_TRIGGER = 0.7

# Homeostatic target mean (same as homeostatic_plasticity._TARGET_HEAT).
_TARGET_HEAT = 0.4

# Fold trigger: when |log(factor)| > log(2.0), the scalar has drifted
# into prefilter-distorting territory.
_FOLD_LOG_THRESHOLD = math.log(2.0)

# Minimum mean-effective-heat before the scaling divisor is numerically
# safe. Below this we skip the cycle rather than amplify noise.
_MIN_SAFE_MEAN = 0.01

# Per-cycle cap on the multiplicative step relative to the current factor.
# Matches the legacy Turrigiano α=0.05 ceiling (~3% per cycle).
_MAX_STEP = 0.03


def run_homeostatic_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Update the domain's homeostatic factor; fold if drift is too large.

    Branching:
      1. healthy AND unimodal → no-op
      2. bimodal → cohort correction (per-row writes via bump_heat_raw)
      3. off-target → scalar factor update, fold if drift > log(2.0)

    Phase 4: when the caller passes ``memories=None`` we compute the
    health metrics via a streaming server-side cursor
    (``store.iter_memories_for_decay``) + Welford moments. Peak memory
    is O(chunk_size) instead of O(N) — crucial at 66K+ memory stores.
    When the caller passes a pre-loaded list (hot-path consolidate
    sharing one snapshot across stages), we use it directly.

    Returns:
        scaling_applied: bool
        scaling_kind: "none" | "cohort_correction" | "scalar_update" | "fold"
        health_score, mean_heat, std_heat, bimodality, memories_scanned
    """
    try:
        if memories is None:
            # Streaming path: compute health without materializing.
            health, count = _streaming_health(store)
            if count == 0:
                return {
                    "scaling_applied": False,
                    "scaling_kind": "none",
                    "health_score": None,
                    "reason": "no_memories",
                    "memories_scanned": 0,
                }
            # For dispatch we still need the memory list for the cohort
            # branch (needs ids + per-row heats). Only materialize when
            # bimodality triggers cohort path.
            if health["bimodality_coefficient"] > _BIMODALITY_TRIGGER:
                memories = store.get_all_memories_for_decay()
            else:
                memories = []  # not needed for scalar / no-op paths
        else:
            if not memories:
                return {
                    "scaling_applied": False,
                    "scaling_kind": "none",
                    "health_score": None,
                    "reason": "no_memories",
                    "memories_scanned": 0,
                }
            heats = [m.get("heat", 0.5) for m in memories]
            health = homeostatic_health.compute_distribution_health(
                heats, target_mean=_TARGET_HEAT
            )

        heats = [m.get("heat", 0.5) for m in memories] if memories else []
        outcome = _dispatch(store, memories, heats, health)
        _log_diagnostics(outcome)

        return {
            **outcome,
            "health_score": health["health_score"],
            "mean_heat": health["mean"],
            "std_heat": health["std"],
            "bimodality": health["bimodality_coefficient"],
            "memories_scanned": len(memories) if memories else -1,
        }
    except Exception as exc:
        logger.warning("Homeostatic cycle failed: %s", exc, exc_info=True)
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "health_score": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _streaming_health(store: MemoryStore) -> tuple[dict, int]:
    """Compute distribution health via server-side cursor + Welford moments.

    Uses ``store.iter_memories_for_decay`` when available (Phase 4);
    falls back to full materialization for SQLite / test fake stores.
    """
    if not hasattr(store, "iter_memories_for_decay"):
        memories = store.get_all_memories_for_decay()
        heats = [m.get("heat", 0.5) for m in memories]
        health = homeostatic_health.compute_distribution_health(
            heats, target_mean=_TARGET_HEAT
        )
        return health, len(heats)

    def _heat_chunks():
        for chunk in store.iter_memories_for_decay():
            yield [m.get("heat", 0.5) for m in chunk]

    return homeostatic_health.compute_distribution_health_streaming(
        _heat_chunks(), target_mean=_TARGET_HEAT
    )


def _dispatch(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    health: dict,
) -> dict:
    """Pick the right primitive given distribution health."""
    bimodality = health["bimodality_coefficient"]
    mean = health["mean"]
    std = health["std"]

    if health["health_score"] >= 0.6 and bimodality <= _BIMODALITY_TRIGGER:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
        }

    if bimodality > _BIMODALITY_TRIGGER:
        return _apply_cohort(store, memories, heats, mean, std, bimodality)

    return _apply_scalar(store, memories, mean, bimodality)


# ── Scalar + fold ────────────────────────────────────────────────────────


def _apply_scalar(
    store: MemoryStore,
    memories: list[dict],
    mean: float,
    bimodality: float,
) -> dict:
    """One UPDATE on homeostatic_state.factor + optional fold.

    Replaces the legacy N-row Turrigiano UPDATE with one scalar write.
    Fold (factor ∉ [0.5, 2.0]) writes heat_base per-row and resets
    factor=1.0 — expected ~once/month per domain.
    """
    if mean <= _MIN_SAFE_MEAN:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
            "reason_for_zero": "mean_below_safety_floor",
        }

    domain = _dominant_domain(memories)
    factor_old = _safe_get_factor(store, domain)
    factor_new = factor_old * (_TARGET_HEAT / mean)
    factor_new = _clamp_step(factor_old, factor_new, max_step=_MAX_STEP)

    if abs(factor_new - factor_old) <= 0.005 * max(factor_old, 1e-6):
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
            "reason_for_zero": "factor_stable",
            "factor": round(factor_old, 4),
        }

    if _fold_triggered(factor_new):
        folded = _apply_fold(store, domain, factor_new)
        return {
            "scaling_applied": True,
            "scaling_kind": "fold",
            "bimodality_before": bimodality,
            "bimodality_after": None,
            "factor_pre_fold": round(factor_new, 4),
            "rows_folded": folded,
        }

    store.set_homeostatic_factor(domain, factor_new)
    return {
        "scaling_applied": True,
        "scaling_kind": "scalar_update",
        "bimodality_before": bimodality,
        "bimodality_after": None,
        "factor": round(factor_new, 4),
        "factor_delta": round(factor_new - factor_old, 4),
    }


def _fold_triggered(factor: float) -> bool:
    """Fold when |log(factor)| > log(2.0) — factor ∉ [0.5, 2.0]."""
    if factor <= 0.0:
        return False
    return abs(math.log(factor)) > _FOLD_LOG_THRESHOLD


def _apply_fold(store: MemoryStore, domain: str, factor: float) -> int:
    """Multiply heat_base by factor, reset homeostatic_state.factor=1.0.

    Writes are bounded by the domain partition, skip protected/no_decay/stale.
    Amortized once per month per domain under normal operation.
    Phase 5: batched UPDATE runs on the batch pool.
    """
    with store.acquire_batch() as conn:
        result = conn.execute(
            "UPDATE memories "
            "SET heat_base = LEAST(1.0, GREATEST(0.0, heat_base * %s)), "
            "    heat_base_set_at = NOW() "
            "WHERE domain = %s "
            "  AND NOT is_protected "
            "  AND NOT no_decay "
            "  AND NOT is_stale",
            (float(factor), domain or ""),
        )
        rows = int(getattr(result, "rowcount", 0) or 0)
    store.set_homeostatic_factor(domain, 1.0)
    return rows


def _dominant_domain(memories: list[dict]) -> str:
    """Pick the most-frequent domain as the scaling key."""
    counts: dict[str, int] = {}
    for mem in memories:
        d = mem.get("domain") or ""
        counts[d] = counts.get(d, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _safe_get_factor(store: MemoryStore, domain: str) -> float:
    try:
        return float(store.get_homeostatic_factor(domain))
    except Exception as exc:
        logger.debug("get_homeostatic_factor(%r) failed: %s", domain, exc)
        return 1.0


def _clamp_step(old: float, new: float, max_step: float) -> float:
    """Cap the per-cycle multiplicative step at ±max_step relative to old."""
    if old <= 0.0:
        return new
    ratio = new / old
    ratio = max(1.0 - max_step, min(1.0 + max_step, ratio))
    return old * ratio


# ── Bimodal cohort path ──────────────────────────────────────────────────


def _apply_cohort(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    mean: float,
    std: float,
    bimodality: float,
) -> dict:
    """Bimodal path: pull the hot cohort toward target_mean.

    Per-row writes route through ``bump_heat_raw`` (the I2 canonical
    writer). Subtraction is not meaningful on a scalar factor, so this
    branch writes heat_base directly.
    """
    cohort_idx = homeostatic_plasticity.detect_hot_cohort(heats, mean, std)
    if not cohort_idx:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
            "reason_for_zero": "bimodal_but_no_cohort_detected",
        }
    scaled = homeostatic_plasticity.apply_cohort_correction(
        heats, cohort_idx, target_mean=_TARGET_HEAT
    )
    after = homeostatic_health.compute_distribution_health(
        scaled, target_mean=_TARGET_HEAT
    )
    for i, new_heat in enumerate(scaled):
        if abs(new_heat - heats[i]) > 0.001:
            store.bump_heat_raw(memories[i]["id"], round(new_heat, 4))
    return {
        "scaling_applied": True,
        "scaling_kind": "cohort_correction",
        "bimodality_before": bimodality,
        "bimodality_after": after["bimodality_coefficient"],
        "cohort_size": len(cohort_idx),
    }


def _log_diagnostics(outcome: dict) -> None:
    if (
        outcome.get("scaling_kind") == "cohort_correction"
        and outcome.get("bimodality_after") is not None
        and outcome["bimodality_after"] >= outcome["bimodality_before"]
    ):
        logger.warning(
            "Cohort correction did not reduce bimodality: "
            "before=%.3f after=%.3f cohort_size=%s",
            outcome["bimodality_before"],
            outcome["bimodality_after"],
            outcome.get("cohort_size"),
        )
    if outcome.get("scaling_kind") == "fold":
        logger.info(
            "Homeostatic fold triggered: factor_pre_fold=%.4f rows_folded=%d",
            outcome.get("factor_pre_fold", 0.0),
            outcome.get("rows_folded", 0),
        )
