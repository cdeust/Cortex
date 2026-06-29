"""Core tests for the two-circuit active-forgetting decisions.

Pure maths, no I/O: the redundancy-gated chronic signal, the leaky-integrator
accumulator, and the two reversible decisions. Constants come from the
by-construction benchmark (benchmarks/active_forgetting/run_benchmark.py).
"""

from __future__ import annotations

import pytest

from mcp_server.core.active_forgetting import (
    ACUTE_OVERLAP_THRESHOLD,
    ACUTE_RECENCY_WINDOW_HOURS,
    PERMANENT_ACCUM_THRESHOLD,
    PRESSURE_LEAK_LAMBDA,
    TAU_DUP,
    chronic_interference,
    forgetting_pressure,
    is_permanent_forgetting,
    is_transient_forgetting,
    update_pressure_accum,
)
from mcp_server.core.curation import MERGE_THRESHOLD


# ── chronic_interference (redundancy-gated excess noisy-OR) ────────────────


def test_tau_dup_is_the_curation_cutoff():
    """τ_dup is not a free constant — it reuses the committed curation cutoff."""
    assert TAU_DUP == MERGE_THRESHOLD


def test_background_band_yields_zero():
    """The ~0.5 similarity floor of 384-dim embeddings contributes nothing."""
    assert chronic_interference([0.52, 0.61, 0.48, 0.55, 0.67]) == 0.0


def test_just_below_tau_is_excluded():
    """Membership gate, not a rescale: 0.84 (< 0.85) does not contribute."""
    assert chronic_interference([0.84, 0.83, 0.82]) == 0.0


def test_empty_is_zero():
    assert chronic_interference([]) == 0.0


def test_single_near_dup_is_excess_over_floor():
    """One 0.95 dup → (0.95-0.85)/(1-0.85) = 0.6667."""
    assert chronic_interference([0.95]) == pytest.approx((0.95 - 0.85) / 0.15)


def test_monotone_in_count_of_near_dups():
    """Two genuine dups interfere more than one (noisy-OR over the dup set)."""
    one = chronic_interference([0.95])
    two = chronic_interference([0.95, 0.92])
    assert two > one


def test_background_field_with_one_dup_does_not_saturate_below_dup_value():
    """A field of background neighbours plus one dup equals just the dup's term —
    the saturation guard: background never inflates the signal."""
    field = chronic_interference([0.5] * 20 + [0.95])
    assert field == pytest.approx(chronic_interference([0.95]))


def test_clamps_negative_and_above_one():
    assert chronic_interference([-0.5, 0.3]) == 0.0
    assert chronic_interference([1.5]) == pytest.approx(1.0)


# ── forgetting_pressure (chronic × stage vulnerability) ────────────────────


def test_pressure_graded_by_stage():
    """Same chronic, decreasing vulnerability labile → consolidated."""
    labile = forgetting_pressure("labile", 0.8)
    consolidated = forgetting_pressure("consolidated", 0.8)
    assert labile > consolidated > 0.0


def test_zero_chronic_zero_pressure():
    assert forgetting_pressure("labile", 0.0) == 0.0


# ── update_pressure_accum (leaky integrator) ───────────────────────────────


def test_accumulator_leaks_when_no_pressure():
    """chronic 0 → accum = λ·prev (leak-down, not reset)."""
    assert update_pressure_accum(1.0, "labile", 0.0, False) == pytest.approx(
        PRESSURE_LEAK_LAMBDA
    )


def test_sleep_protected_cycle_adds_no_pressure_and_leaks():
    """recently_active zeroes pressure even under strong chronic."""
    assert update_pressure_accum(1.0, "labile", 0.95, True) == pytest.approx(
        PRESSURE_LEAK_LAMBDA
    )


def test_sustained_pressure_reaches_steady_state():
    """Repeated pressure converges to p/(1-λ); single bout cannot reach it."""
    accum = 0.0
    for _ in range(50):
        accum = update_pressure_accum(accum, "labile", 0.667, False)
    p = forgetting_pressure("labile", 0.667)
    assert accum == pytest.approx(p / (1 - PRESSURE_LEAK_LAMBDA), rel=1e-3)


# ── is_permanent_forgetting (sustained accumulator decision) ───────────────


def test_permanent_fires_above_threshold():
    assert is_permanent_forgetting(PERMANENT_ACCUM_THRESHOLD + 0.1, False, False)


def test_permanent_quiet_below_threshold():
    assert not is_permanent_forgetting(PERMANENT_ACCUM_THRESHOLD - 0.1, False, False)


def test_pinned_and_sleep_exempt_permanent():
    high = PERMANENT_ACCUM_THRESHOLD + 1.0
    assert not is_permanent_forgetting(high, True, False)
    assert not is_permanent_forgetting(high, False, True)


def test_single_bout_never_fires_permanent():
    """One strong cycle from zero stays below Θ (the saturation/over-fire fix)."""
    accum = update_pressure_accum(0.0, "labile", 0.95, False)
    assert not is_permanent_forgetting(accum, False, False)


# ── is_transient_forgetting (acute, stage-independent) ─────────────────────


def test_transient_needs_overlap_and_recency():
    assert is_transient_forgetting(0.9, 1.0, False, False)
    assert not is_transient_forgetting(0.9, ACUTE_RECENCY_WINDOW_HOURS + 1, False, False)
    assert not is_transient_forgetting(ACUTE_OVERLAP_THRESHOLD - 0.01, 1.0, False, False)


def test_transient_pinned_and_recovered_exempt():
    assert not is_transient_forgetting(0.9, 1.0, True, False)
    assert not is_transient_forgetting(0.9, 1.0, False, True)
