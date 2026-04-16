"""Homeostatic plasticity — distribution health metrics.

Split from homeostatic_plasticity.py to keep files under 300 lines.
Computes statistical health metrics for value distributions (heats, weights)
to determine whether homeostatic mechanisms need to intervene.

References:
    Pfister R et al. (2013) Good things peak in pairs: a note on the
        bimodality coefficient. Frontiers in Psychology 4:700
    Pébay P (2008) Formulas for Robust, One-Pass Parallel Computation of
        Covariances and Arbitrary-Order Statistical Moments. Sandia Report
        SAND2008-6212. Equations 2.1 (M1), 2.2 (M2), 2.3 (M3), 2.4 (M4).

Pure business logic — no I/O.
"""

from __future__ import annotations

import math


def _compute_moments(
    values: list[float],
) -> tuple[float, float, float, float]:
    """Compute mean, std, skewness, and excess kurtosis in a single pass.

    Uses Welford's online algorithm extended to third and fourth central
    moments (Pébay 2008, §2, equations 2.1–2.4). We maintain running
    ``M2`` (sum of squared deviations), ``M3`` (sum of cubed deviations),
    and ``M4`` (sum of quartic deviations) via the incremental update
    formulas. This is numerically stable and touches each value once —
    four generator-expression passes over the full list are gone.

    Equations (Pébay 2008, after observing the n-th value ``x``):
        delta   = x - M1_{n-1}
        delta_n = delta / n
        term1   = delta * delta_n * (n-1)
        M1_n    = M1_{n-1} + delta_n
        M4_n    = M4_{n-1} + term1 * delta_n^2 * (n^2 - 3n + 3)
                + 6 * delta_n^2 * M2_{n-1} - 4 * delta_n * M3_{n-1}
        M3_n    = M3_{n-1} + term1 * delta_n * (n-2) - 3 * delta_n * M2_{n-1}
        M2_n    = M2_{n-1} + term1

    After the loop, the variance, skewness and excess-kurtosis estimators
    match the biased-n formulations used by the original implementation:
        variance    = M2 / (n-1)        — sample variance
        skew        = M3 / (n * std^3)
        kurtosis_ex = M4 / (n * std^4) - 3.0

    Args:
        values: Non-empty list of numeric values.

    Returns:
        Tuple of (mean, std, skew, kurtosis_excess). For empty input
        returns (0, 0, 0, 0).

    Precondition: values is iterable of finite floats.
    Postcondition: results are within 1e-9 of the four-pass implementation
        on any well-conditioned input (Pébay 2008, §4 stability analysis).
    Invariant (per iteration): after processing n values, (m1, M2, M3, M4)
        equal the exact running moments for the first n values.
    """
    n = 0
    m1 = 0.0
    m2 = 0.0
    m3 = 0.0
    m4 = 0.0

    for x in values:
        n1 = n
        n += 1
        delta = x - m1
        delta_n = delta / n
        delta_n2 = delta_n * delta_n
        term1 = delta * delta_n * n1  # (x - m1_old) * delta_n * (n-1)

        # Fourth moment must be updated before M3 and M2 (depends on old M2, M3).
        m4 += (
            term1 * delta_n2 * (n * n - 3 * n + 3)
            + 6.0 * delta_n2 * m2
            - 4.0 * delta_n * m3
        )
        # Third moment depends on old M2, must precede M2 update.
        m3 += term1 * delta_n * (n - 2) - 3.0 * delta_n * m2
        m2 += term1
        m1 += delta_n

    if n == 0:
        return 0.0, 0.0, 0.0, 0.0

    variance = m2 / max(n - 1, 1)
    std = math.sqrt(variance)

    if std > 1e-10:
        skew = m3 / (n * std**3)
        kurtosis = m4 / (n * std**4) - 3.0
    else:
        skew = 0.0
        kurtosis = 0.0

    return m1, std, skew, kurtosis


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
