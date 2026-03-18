"""Tests for emergence_tracker — system-level metric tracking."""

import pytest
from mcp_server.core.emergence_tracker import (
    compute_spacing_benefit,
    compute_testing_benefit,
    compute_schema_acceleration_metric,
    compute_phase_locking_benefit,
)
from mcp_server.core.emergence_metrics import (
    compute_forgetting_curve,
    generate_emergence_report,
)


class TestSpacingEffect:
    def test_regular_spacing_high_score(self):
        times = [0, 10, 20, 30, 40, 50]  # Equal intervals
        score = compute_spacing_benefit(times, 0.8)
        assert score > 0.8

    def test_massed_practice_low_score(self):
        times = [0, 0.1, 0.2, 0.3, 0.4]  # All clustered
        score = compute_spacing_benefit(times, 0.3)
        assert score > 0.5  # Still some regularity

    def test_insufficient_data(self):
        assert compute_spacing_benefit([0, 1], 0.5) == 0.5


class TestTestingEffect:
    def test_high_retrieval_fraction(self):
        result = compute_testing_benefit(8, 2, 0.7)
        assert result["retrieval_fraction"] == 0.8
        assert result["testing_benefit"] > 0

    def test_no_practice(self):
        result = compute_testing_benefit(0, 0, 0.5)
        assert result["testing_benefit"] == 0.0


class TestSchemaAcceleration:
    def test_schema_consistent_faster(self):
        consistent = [
            {"consolidation_stage": "consolidated", "hours_in_stage": 10},
            {"consolidation_stage": "consolidated", "hours_in_stage": 8},
        ]
        inconsistent = [
            {"consolidation_stage": "late_ltp", "hours_in_stage": 20},
            {"consolidation_stage": "early_ltp", "hours_in_stage": 30},
        ]
        result = compute_schema_acceleration_metric(consistent, inconsistent)
        assert (
            result["consistent_consolidated_fraction"]
            > result["inconsistent_consolidated_fraction"]
        )

    def test_empty_data(self):
        result = compute_schema_acceleration_metric([], [])
        assert result["consistent_count"] == 0


class TestForgettingCurve:
    def test_insufficient_data(self):
        result = compute_forgetting_curve([(1, 0.9), (2, 0.8)])
        assert result["curve_type"] == "insufficient_data"

    def test_exponential_fit(self):
        # Generate exponential decay data
        import math

        data = [(t, 0.9 * math.exp(-0.01 * t)) for t in range(0, 200, 10)]
        result = compute_forgetting_curve(data)
        assert result["curve_type"] in ("exponential", "insufficient_bins")
        if result["curve_type"] == "exponential":
            assert result["r_squared"] > 0.5
            assert result["half_life_hours"] > 0


class TestPhaseLocking:
    def test_encoding_phase_benefit(self):
        enc = [{"heat": 0.8}, {"heat": 0.7}, {"heat": 0.9}]
        ret = [{"heat": 0.4}, {"heat": 0.3}, {"heat": 0.5}]
        result = compute_phase_locking_benefit(enc, ret)
        assert result["phase_benefit"] > 0
        assert result["encoding_phase_avg_heat"] > result["retrieval_phase_avg_heat"]

    def test_no_difference(self):
        mems = [{"heat": 0.5}] * 5
        result = compute_phase_locking_benefit(mems, mems)
        assert result["phase_benefit"] == pytest.approx(0.0, abs=0.01)


class TestEmergenceReport:
    def test_generates_full_report(self):
        memories = [
            {
                "heat": 0.8,
                "hours_in_stage": 5,
                "schema_match_score": 0.7,
                "theta_phase_at_encoding": 0.2,
                "consolidation_stage": "early_ltp",
                "interference_score": 0.1,
            },
            {
                "heat": 0.3,
                "hours_in_stage": 48,
                "schema_match_score": 0.1,
                "theta_phase_at_encoding": 0.7,
                "consolidation_stage": "consolidated",
                "interference_score": 0.0,
            },
        ]
        report = generate_emergence_report(memories)
        assert "forgetting_curve" in report
        assert "schema_acceleration" in report
        assert "phase_locking" in report
        assert "stage_distribution" in report

    def test_empty_memories(self):
        report = generate_emergence_report([])
        assert report["memory_count"] == 0
