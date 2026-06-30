"""Unit tests for the forgetting-curve Benna&Fusi √t law-family criterion.

Pure logic — no DB. Drives criterion_benna_fusi_sqrt_t with synthetic mixture
trajectories of known form to prove the criterion accepts a true 1/√t power
law and rejects a single exponential. Locks the falsifier so a future change
to the α-ladder that accidentally fakes (or genuinely earns) a power law is
caught.
"""

from __future__ import annotations

import math

from benchmarks.forgetting_curve import criteria
from benchmarks.forgetting_curve.criteria import PROFILES

AGES = [2, 4, 8, 16, 32, 64, 128, 256]


def _uniform_trajs(curve_fn) -> dict[str, list[dict]]:
    """All 4 stage profiles follow the same h(t); the mixture mean is h(t)."""
    return {
        name: [{"age_hours": t, "heat": curve_fn(t), "stage": name} for t in AGES]
        for name in PROFILES
    }


def test_sqrt_t_mixture_passes() -> None:
    """A pure 1/√t mixture: power law wins and b lands in the √t band."""
    trajs = _uniform_trajs(lambda t: 0.95 * t**-0.5)
    c4 = criteria.criterion_benna_fusi_sqrt_t(trajs, AGES)
    assert c4["passed"] is True
    assert c4["comparison"]["winner"] == "power_law"
    assert criteria.SQRT_T_B_LOW <= c4["power_b_exponent"] <= criteria.SQRT_T_B_HIGH
    # b must be near 0.5 — the recovered exponent of the planted law.
    assert abs(c4["power_b_exponent"] - 0.5) < 0.05


def test_single_exponential_mixture_fails() -> None:
    """A single-exponential mixture is NOT the √t family — criterion fails."""
    trajs = _uniform_trajs(lambda t: 0.95 * math.exp(-0.05 * t))
    c4 = criteria.criterion_benna_fusi_sqrt_t(trajs, AGES)
    assert c4["passed"] is False
    assert c4["comparison"]["winner"] == "exponential"


def test_out_of_band_power_law_fails() -> None:
    """A power law with the wrong exponent (b≈1.5, steeper than √t) wins over
    exponential but falls outside the √t band — falsified as a √t law."""
    trajs = _uniform_trajs(lambda t: 0.95 * t**-1.5)
    c4 = criteria.criterion_benna_fusi_sqrt_t(trajs, AGES)
    assert c4["comparison"]["winner"] == "power_law"
    assert c4["power_b_in_sqrt_t_band"] is False
    assert c4["passed"] is False


def test_verdict_appends_sqrt_t_clause() -> None:
    """verdict() must surface the √t finding regardless of C1/C2 outcome."""
    pass_c = {"passed": True}
    bf_pass = {
        "passed": True,
        "power_b_exponent": 0.5,
        "comparison": {"winner": "power_law"},
    }
    bf_fail = {
        "passed": False,
        "power_b_exponent": 0.12,
        "comparison": {"winner": "exponential"},
    }
    assert "√t law-family CONFIRMED" in criteria.verdict(pass_c, pass_c, bf_pass)
    assert "√t law-family NOT reproduced" in criteria.verdict(pass_c, pass_c, bf_fail)
