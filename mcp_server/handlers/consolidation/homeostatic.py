"""Homeostatic cycle: synaptic scaling and BCM threshold updates.

Prevents runaway heat distributions by scaling memory heats toward a
target mean. For bimodal distributions — typical after a batch backfill
at baseline heat=1.0 — falls back to subtractive cohort correction
because Turrigiano multiplicative scaling is order-preserving and
cannot merge modes (Tetzlaff et al. 2011 Eq. 3).

Source: issue #14 P1 — darval's v3.12.0 field report showed
`scaling_applied: true` with `bimodality: 0.85`, recall pinned to the
import cohort. Root cause: multiplicative scaling factor ≈ (1 ± 0.03)
preserves relative ordering of two peaks; one cycle shifts them both
equally and never merges them. Fix: detect bimodality, switch primitive.
"""

from __future__ import annotations

import logging

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


def run_homeostatic_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Apply the appropriate homeostatic primitive for the current distribution.

    Returns a dict with at least:
      - scaling_applied: bool   (backward compat; True iff heats changed)
      - scaling_kind: "none" | "multiplicative" | "cohort_correction"
      - health_score: float | None
      - bimodality_before: float
      - bimodality_after: float | None  (only when cohort_correction ran)
      - cohort_size: int | None         (only when cohort_correction ran)

    See issue #14 and #13 for motivation: multiplicative scaling cannot
    flatten the sharp peak produced by bulk backfills at baseline heat=1.0;
    detect that case via bimodality coefficient and switch primitives.
    Surfaces failures explicitly (same contract as pre-#14) — previous
    versions silently swallowed exceptions with logger.debug.
    """
    try:
        if memories is None:
            memories = store.get_all_memories_for_decay()
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
            heats,
            target_mean=_TARGET_HEAT,
        )

        outcome = _maybe_apply_scaling(store, memories, heats, health)

        # Diagnostic: cohort correction ran but did not reduce bimodality.
        # That's a signal the primitive or thresholds need tuning.
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

        return {
            **outcome,
            "health_score": health["health_score"],
            "mean_heat": health["mean"],
            "std_heat": health["std"],
            "bimodality": health["bimodality_coefficient"],
            "memories_scanned": len(memories),
        }
    except Exception as exc:
        logger.warning("Homeostatic cycle failed: %s", exc, exc_info=True)
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "health_score": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _apply_multiplicative(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    mean: float,
    bimodality: float,
) -> dict:
    """Classic Turrigiano scaling path. Unimodal, unhealthy distributions."""
    factor = homeostatic_plasticity.compute_scaling_factor(
        mean, target_heat=_TARGET_HEAT
    )
    if abs(factor - 1.0) <= 0.005:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
        }
    scaled = homeostatic_plasticity.apply_synaptic_scaling(heats, factor)
    # TODO(A3): lazy heat eliminates this per-row write
    for mem, new_heat in zip(memories, scaled):
        if abs(new_heat - mem.get("heat", 0)) > 0.001:
            store.update_memory_heat(mem["id"], round(new_heat, 4))
    return {
        "scaling_applied": True,
        "scaling_kind": "multiplicative",
        "bimodality_before": bimodality,
        "bimodality_after": None,
        "scaling_factor": round(factor, 4),
    }


def _apply_cohort(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    mean: float,
    std: float,
    bimodality: float,
) -> dict:
    """Bimodal path: pull the hot cohort toward the target mean."""
    cohort_idx = homeostatic_plasticity.detect_hot_cohort(heats, mean, std)
    if not cohort_idx:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
            "reason": "bimodal_but_no_cohort_detected",
        }
    scaled = homeostatic_plasticity.apply_cohort_correction(
        heats, cohort_idx, target_mean=_TARGET_HEAT
    )
    after = homeostatic_health.compute_distribution_health(
        scaled, target_mean=_TARGET_HEAT
    )
    # TODO(A3): lazy heat eliminates this per-row write
    for i, new_heat in enumerate(scaled):
        if abs(new_heat - heats[i]) > 0.001:
            store.update_memory_heat(memories[i]["id"], round(new_heat, 4))
    return {
        "scaling_applied": True,
        "scaling_kind": "cohort_correction",
        "bimodality_before": bimodality,
        "bimodality_after": after["bimodality_coefficient"],
        "cohort_size": len(cohort_idx),
    }


def _maybe_apply_scaling(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    health: dict,
) -> dict:
    """Pick the right primitive given distribution health.

    Branching:
      1. healthy AND unimodal → no-op
      2. bimodal → cohort correction (Turrigiano cannot merge modes)
      3. unimodal but off-target → classic multiplicative scaling
    """
    bimodality = health["bimodality_coefficient"]
    mean = health["mean"]
    std = health["std"]

    # Branch 1: healthy and unimodal — no action.
    if health["health_score"] >= 0.6 and bimodality <= _BIMODALITY_TRIGGER:
        return {
            "scaling_applied": False,
            "scaling_kind": "none",
            "bimodality_before": bimodality,
            "bimodality_after": None,
        }

    # Branch 2: bimodal — cohort correction.
    if bimodality > _BIMODALITY_TRIGGER:
        return _apply_cohort(store, memories, heats, mean, std, bimodality)

    # Branch 3: unimodal but off-target — classic multiplicative scaling.
    return _apply_multiplicative(store, memories, heats, mean, bimodality)
