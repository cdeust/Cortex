"""Homeostatic plasticity — distribution health metrics.

Split from homeostatic_plasticity.py to keep files under 300 lines.
Computes statistical health metrics for value distributions (heats, weights)
to determine whether homeostatic mechanisms need to intervene.

References:
    Pfister R et al. (2013) Good things peak in pairs: a note on the
        bimodality coefficient. Frontiers in Psychology 4:700

Pure business logic — no I/O.
"""

from __future__ import annotations

import math


def _compute_moments(
    values: list[float],
) -> tuple[float, float, float, float]:
    """Compute mean, std, skewness, and excess kurtosis.

    Args:
        values: Non-empty list of numeric values.

    Returns:
        Tuple of (mean, std, skew, kurtosis_excess).
    """
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / max(n - 1, 1)
    std = math.sqrt(variance)

    if std > 1e-10:
        skew = sum((v - mean) ** 3 for v in values) / (n * std**3)
        kurtosis = sum((v - mean) ** 4 for v in values) / (n * std**4) - 3.0
    else:
        skew = 0.0
        kurtosis = 0.0

    return mean, std, skew, kurtosis


def _compute_health_score(
    deviation: float,
    bimodality: float,
    skew: float,
    std: float,
) -> float:
    """Compute overall health score from distribution statistics.

    Health = 1.0 (perfectly healthy) to 0.0 (needs intervention).
    Penalizes: high deviation, high bimodality, extreme skew, low variance.

    Args:
        deviation: Absolute deviation from target mean.
        bimodality: Bimodality coefficient.
        skew: Distribution skewness.
        std: Standard deviation.

    Returns:
        Health score clamped to [0, 1].
    """
    health = 1.0
    health -= min(deviation * 2.0, 0.4)
    health -= min(max(bimodality - 0.4, 0) * 1.5, 0.3)
    health -= min(abs(skew) * 0.15, 0.2)
    if std < 0.05:
        health -= 0.1
    return max(0.0, min(1.0, health))


_EMPTY_HEALTH = {
    "mean": 0.0,
    "std": 0.0,
    "skew": 0.0,
    "kurtosis_excess": 0.0,
    "deviation_from_target": 1.0,
    "bimodality_coefficient": 0.0,
    "health_score": 0.0,
}


def compute_distribution_health(
    values: list[float],
    target_mean: float,
) -> dict[str, float]:
    """Compute health metrics for a distribution of values (heats, weights, etc.).

    Returns metrics that indicate whether homeostatic mechanisms are needed.

    Args:
        values: List of values (e.g., heats).
        target_mean: Desired mean value.

    Returns:
        Dict with: mean, std, skew, kurtosis_excess, deviation_from_target,
        bimodality_coefficient, health_score (0=unhealthy, 1=healthy).
    """
    if not values:
        return dict(_EMPTY_HEALTH)

    mean, std, skew, kurtosis = _compute_moments(values)
    bimodality = (skew**2 + 1) / max(kurtosis + 3, 0.01)
    deviation = abs(mean - target_mean)
    health = _compute_health_score(deviation, bimodality, skew, std)

    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "skew": round(skew, 4),
        "kurtosis_excess": round(kurtosis, 4),
        "deviation_from_target": round(deviation, 4),
        "bimodality_coefficient": round(bimodality, 4),
        "health_score": round(health, 4),
    }
