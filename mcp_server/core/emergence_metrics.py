"""Emergence tracker — forgetting curve fitting and aggregate report.

Split from emergence_tracker.py to keep files under 300 lines.
Contains the forgetting curve analysis (log-linear regression) and the
aggregate emergence report generator.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# ── Forgetting Curve ─────────────────────────────────────────────────────


def _bin_memories_by_age(
    memories_by_age: list[tuple[float, float]],
    bin_width_hours: float = 6.0,
) -> list[tuple[float, float]]:
    """Bin memories by age and compute average heat per bin.

    Args:
        memories_by_age: List of (age_hours, heat) tuples.
        bin_width_hours: Width of each bin in hours.

    Returns:
        List of (bin_center_hours, mean_heat) tuples, sorted by age.
    """
    bins: dict[int, list[float]] = {}
    for age, heat in memories_by_age:
        bin_idx = max(0, int(age / bin_width_hours))
        bins.setdefault(bin_idx, []).append(heat)

    return [
        (bin_idx * bin_width_hours + bin_width_hours / 2, sum(heats) / len(heats))
        for bin_idx, heats in sorted(bins.items())
    ]


_DEGENERATE_RESULT = {
    "curve_type": "degenerate",
    "r_squared": 0.0,
    "fit_quality": "degenerate",
    "half_life_hours": 0.0,
    "retention_at_24h": 0.0,
}


def _ols_sums(
    log_heats: list[tuple[float, float]],
) -> tuple[int, float, float, float, float]:
    """Compute OLS summary statistics."""
    n = len(log_heats)
    sum_x = sum(t for t, _ in log_heats)
    sum_y = sum(y for _, y in log_heats)
    sum_xy = sum(t * y for t, y in log_heats)
    sum_x2 = sum(t * t for t, _ in log_heats)
    return n, sum_x, sum_y, sum_xy, sum_x2


def _fit_log_linear(
    log_heats: list[tuple[float, float]],
) -> dict[str, float]:
    """Fit log-linear regression: log(heat) = log(a) - b * age via OLS.

    Returns dict with curve_type, r_squared, half_life_hours,
    retention_at_24h, decay_rate, initial_retention, and a
    ``fit_quality`` flag (darval's v3.13.2 P3 — signal when r²
    is too low to trust the derived metrics).
    """
    n, sum_x, sum_y, sum_xy, sum_x2 = _ols_sums(log_heats)

    denom = n * sum_x2 - sum_x**2
    if abs(denom) < 1e-10:
        return dict(_DEGENERATE_RESULT)

    b = -(n * sum_xy - sum_x * sum_y) / denom
    log_a = (sum_y + b * sum_x) / n
    a = math.exp(log_a)

    mean_y = sum_y / n
    ss_tot = sum((y - mean_y) ** 2 for _, y in log_heats)
    ss_res = sum((y - (log_a - b * t)) ** 2 for t, y in log_heats)
    r2 = 1.0 - ss_res / max(ss_tot, 1e-10)
    r2_clamped = max(0.0, r2)

    half_life = math.log(2) / max(b, 1e-10) if b > 0 else float("inf")
    retention_24h = a * math.exp(-b * 24) if b > 0 else a

    return {
        "curve_type": "exponential",
        "r_squared": round(r2_clamped, 4),
        "fit_quality": _fit_quality_for(r2_clamped),
        "half_life_hours": round(min(half_life, 10000), 1),
        "retention_at_24h": round(max(0.0, min(1.0, retention_24h)), 4),
        "decay_rate": round(b, 6),
        "initial_retention": round(min(a, 1.0), 4),
    }


def _fit_quality_for(r_squared: float) -> str:
    """Bucket the fit r² into a consumer-friendly quality label.

    Source: darval's v3.13.2 P3 — "should emergence.forgetting_curve
    gate its derived metrics on a minimum r²?" Answer: emit a label,
    let consumers decide whether to display/ignore.

    Thresholds chosen to be conservative:
      r² < 0.10 → "poor"     — the model explains < 10% of variance;
                               half_life_hours is not meaningful.
      r² < 0.50 → "weak"     — some signal, but a single exponential
                               is an oversimplification.
      else     → "good"      — explains ≥ 50% of variance.
    """
    if r_squared < 0.10:
        return "poor"
    if r_squared < 0.50:
        return "weak"
    return "good"


_INSUFFICIENT = {
    "curve_type": "insufficient_data",
    "r_squared": 0.0,
    "fit_quality": "insufficient_data",
    "half_life_hours": 0.0,
    "retention_at_24h": 0.0,
}


def compute_forgetting_curve(
    memories_by_age: list[tuple[float, float]],
) -> dict[str, float]:
    """Fit a forgetting curve to memory age vs heat data.

    Biology shows power-law forgetting: R(t) = a * t^(-b).
    If Cortex's mechanisms produce a similar curve, the system is
    behaving realistically.

    Args:
        memories_by_age: List of (age_hours, heat) tuples.

    Returns:
        Dict with: curve_type, r_squared, half_life_hours, retention_at_24h.
    """
    if len(memories_by_age) < 5:
        return dict(_INSUFFICIENT)

    bin_means = _bin_memories_by_age(memories_by_age)
    if len(bin_means) < 3:
        return {
            "curve_type": "insufficient_bins",
            "r_squared": 0.0,
            "fit_quality": "insufficient_data",
            "half_life_hours": 0.0,
            "retention_at_24h": 0.0,
        }

    log_heats = [(t, math.log(max(h, 0.01))) for t, h in bin_means if h > 0.01]
    if len(log_heats) < 3:
        return {
            "curve_type": "no_fit",
            "r_squared": 0.0,
            "fit_quality": "insufficient_data",
            "half_life_hours": 0.0,
            "retention_at_24h": 0.0,
        }

    return _fit_log_linear(log_heats)


# ── Aggregate Report ─────────────────────────────────────────────────────


def _compute_stage_distribution(memories: list[dict]) -> dict[str, int]:
    """Count memories per consolidation stage."""
    stages: dict[str, int] = {}
    for m in memories:
        stage = m.get("consolidation_stage", "unknown")
        stages[stage] = stages.get(stage, 0) + 1
    return stages


def _compute_avg_interference(memories: list[dict]) -> float:
    """Compute average interference pressure across memories."""
    scores = [m.get("interference_score", 0) for m in memories]
    return round(sum(scores) / max(len(scores), 1), 4)


def generate_emergence_report(
    memories: list[dict],
    events: list | None = None,
) -> dict:
    """Generate a full emergence report from memory data."""
    from mcp_server.core.emergence_tracker import (
        compute_phase_locking_benefit,
        compute_schema_acceleration_metric,
    )

    age_heat = [
        (m.get("hours_in_stage", 0) + 1.0, m.get("heat", 0.5))
        for m in memories
        if m.get("heat", 0) > 0.01
    ]
    consistent = [m for m in memories if m.get("schema_match_score", 0) >= 0.5]
    inconsistent = [m for m in memories if m.get("schema_match_score", 0) < 0.3]
    enc_phase = [m for m in memories if m.get("theta_phase_at_encoding", 0) < 0.5]
    ret_phase = [m for m in memories if m.get("theta_phase_at_encoding", 0) >= 0.5]

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "memory_count": len(memories),
        "forgetting_curve": compute_forgetting_curve(age_heat),
        "schema_acceleration": compute_schema_acceleration_metric(
            consistent, inconsistent
        ),
        "phase_locking": compute_phase_locking_benefit(enc_phase, ret_phase),
        "stage_distribution": _compute_stage_distribution(memories),
        "avg_interference": _compute_avg_interference(memories),
    }
