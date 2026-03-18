"""Homeostatic plasticity — network-level stability mechanisms.

Without homeostasis, Hebbian learning is unstable: strong memories get stronger
(runaway potentiation), weak memories get weaker (catastrophic depression), and
the system collapses to either all-hot or all-cold. Biology prevents this via
homeostatic mechanisms that maintain target activity levels.

This module implements three homeostatic mechanisms:

1. **Synaptic Scaling (Turrigiano 2008)**
   If a domain's average heat deviates from target, ALL memories in that domain
   get multiplicatively scaled toward the target.

2. **Metaplasticity / BCM Threshold (Abraham & Bear 1996)**
   The sliding modification threshold adjusts based on recent activity.

3. **Intrinsic Excitability Regulation**
   Engram slot excitability is bounded by global statistics.

Distribution health metrics are in homeostatic_health.py.

References:
    Turrigiano GG (2008) The self-tuning neuron. Cell 135:422-435
    Abraham WC, Bear MF (1996) Metaplasticity. Trends Neurosci 19:126-130

Pure business logic — no I/O.
"""

from __future__ import annotations


# ── Configuration ─────────────────────────────────────────────────────────

_TARGET_HEAT = 0.4
_SCALING_RATE = 0.05
_SCALING_DEAD_ZONE = 0.1
_TARGET_EDGE_WEIGHT = 0.5
_BCM_THETA_DECAY = 0.95
_MIN_GLOBAL_EXCITABILITY = 0.1
_MAX_GLOBAL_EXCITABILITY = 0.9
_TARGET_ACTIVE_FRACTION = 0.3


# ── Synaptic Scaling ──────────────────────────────────────────────────────


def compute_scaling_factor(
    current_avg_heat: float,
    target_heat: float = _TARGET_HEAT,
    scaling_rate: float = _SCALING_RATE,
    dead_zone: float = _SCALING_DEAD_ZONE,
) -> float:
    """Compute multiplicative scaling factor for synaptic scaling.

    If avg heat is above target + dead_zone: scale DOWN (factor < 1).
    If avg heat is below target - dead_zone: scale UP (factor > 1).
    Within dead zone: factor = 1.0 (no change).

    Args:
        current_avg_heat: Current average heat across the domain.
        target_heat: Target average heat.
        scaling_rate: Maximum adjustment per cycle.
        dead_zone: Width of the no-adjustment band.

    Returns:
        Multiplicative scaling factor. Apply to all heats in domain.
    """
    deviation = current_avg_heat - target_heat

    if abs(deviation) <= dead_zone:
        return 1.0

    excess = abs(deviation) - dead_zone
    correction = min(excess * scaling_rate / max(current_avg_heat, 0.01), scaling_rate)

    if deviation > 0:
        return 1.0 - correction
    return 1.0 + correction


def apply_synaptic_scaling(
    heats: list[float],
    scaling_factor: float,
) -> list[float]:
    """Apply multiplicative scaling to a list of heat values.

    Preserves relative ordering and clamps to [0, 1].
    """
    return [max(0.0, min(1.0, h * scaling_factor)) for h in heats]


def compute_edge_scaling_factor(
    current_avg_weight: float,
    target_weight: float = _TARGET_EDGE_WEIGHT,
    scaling_rate: float = _SCALING_RATE,
    dead_zone: float = _SCALING_DEAD_ZONE,
) -> float:
    """Compute scaling factor for relationship edge weights.

    Same logic as heat scaling but applied to the knowledge graph.
    """
    return compute_scaling_factor(
        current_avg_weight, target_weight, scaling_rate, dead_zone
    )


# ── Metaplasticity (BCM Threshold) ────────────────────────────────────────


def compute_bcm_threshold(
    recent_activity_levels: list[float],
    current_threshold: float = 0.5,
    decay: float = _BCM_THETA_DECAY,
) -> float:
    """Compute the sliding BCM modification threshold.

    The BCM threshold tracks the square of recent activity levels via EMA.
    High activity -> high threshold -> LTP harder (prevents saturation).
    Low activity -> low threshold -> LTP easier (prevents collapse).

    Args:
        recent_activity_levels: Recent activity levels (e.g., heat values).
        current_threshold: Current BCM threshold.
        decay: EMA decay rate.

    Returns:
        Updated BCM threshold.
    """
    if not recent_activity_levels:
        return current_threshold

    avg_squared = sum(a * a for a in recent_activity_levels) / len(
        recent_activity_levels
    )
    return decay * current_threshold + (1 - decay) * avg_squared


def compute_ltp_ltd_modulation(
    memory_heat: float,
    bcm_threshold: float,
) -> tuple[float, float]:
    """Compute LTP/LTD rate modulation based on BCM threshold.

    Memory activity above threshold -> LTP. Below -> LTD.
    Distance from threshold modulates strength.

    Returns:
        (ltp_multiplier, ltd_multiplier). Both in [0, 2].
    """
    delta = memory_heat - bcm_threshold

    if delta > 0:
        ltp_mult = 1.0 + min(delta * 2.0, 1.0)
        ltd_mult = max(0.2, 1.0 - delta * 2.0)
    else:
        ltd_mult = 1.0 + min(abs(delta) * 2.0, 1.0)
        ltp_mult = max(0.2, 1.0 - abs(delta) * 2.0)

    return ltp_mult, ltd_mult


# ── Intrinsic Excitability Regulation ─────────────────────────────────────


def compute_excitability_adjustment(
    excitabilities: list[float],
    *,
    target_active_fraction: float = _TARGET_ACTIVE_FRACTION,
    active_threshold: float = 0.5,
) -> float:
    """Compute global excitability adjustment for engram slots.

    If too many slots are highly excitable, global excitability should be
    dampened. If too few, boost it.

    Returns:
        Additive adjustment. Positive = boost, negative = dampen.
    """
    if not excitabilities:
        return 0.0

    active_count = sum(1 for e in excitabilities if e >= active_threshold)
    current_fraction = active_count / len(excitabilities)
    deviation = target_active_fraction - current_fraction
    return deviation * 0.1


def apply_excitability_bounds(
    excitability: float,
    adjustment: float = 0.0,
) -> float:
    """Apply global adjustment and clamp excitability to safe bounds."""
    return max(
        _MIN_GLOBAL_EXCITABILITY,
        min(_MAX_GLOBAL_EXCITABILITY, excitability + adjustment),
    )
