"""Tests for precision-weighted prediction errors in hierarchical_predictive_coding.py."""

import pytest

from mcp_server.core.hierarchical_predictive_coding import compute_hierarchical_novelty
from mcp_server.core.predictive_coding_gate import (
    PrecisionState,
    neuromodulate_precisions,
    update_precision_state,
    precision_to_confidence,
    check_calibration,
    calibration_score,
)


# ── Neuromodulate Precisions ─────────────────────────────────────────────


class TestNeuromodulatePrecisions:
    def test_baseline_no_change(self):
        precs = [1.0, 1.0, 1.0]
        result = neuromodulate_precisions(precs, ne_level=1.0, ach_level=0.65)
        # At midpoint, should be close to original
        for r in result:
            assert 0.5 < r < 2.0

    def test_high_ne_amplifies_all(self):
        precs = [1.0, 1.0, 1.0]
        low = neuromodulate_precisions(precs, ne_level=0.5)
        high = neuromodulate_precisions(precs, ne_level=1.8)
        assert all(hi > lo for hi, lo in zip(high, low))

    def test_high_ach_boosts_bottom_up(self):
        precs = [1.0, 1.0, 1.0]
        high_ach = neuromodulate_precisions(precs, ach_level=1.0)
        low_ach = neuromodulate_precisions(precs, ach_level=0.3)
        # L0/L1 should be higher with high ACh
        assert high_ach[0] > low_ach[0]
        assert high_ach[1] > low_ach[1]
        # L2 should be lower with high ACh
        assert high_ach[2] < low_ach[2]

    def test_clamped_to_range(self):
        precs = [0.01, 100.0, 0.01]
        result = neuromodulate_precisions(precs, ne_level=2.0, ach_level=1.0)
        for r in result:
            assert 0.1 <= r <= 10.0


# ── Update Precision State ───────────────────────────────────────────────


class TestUpdatePrecisionState:
    def test_small_errors_increase_precision(self):
        state = PrecisionState(level_precisions=[1.0, 1.0, 1.0])
        updated = update_precision_state(state, [0.01, 0.01, 0.01])
        for old, new in zip(state.level_precisions, updated.level_precisions):
            assert new > old

    def test_large_errors_decrease_precision(self):
        state = PrecisionState(level_precisions=[3.0, 3.0, 3.0])
        updated = update_precision_state(state, [5.0, 5.0, 5.0])
        for old, new in zip(state.level_precisions, updated.level_precisions):
            assert new < old

    def test_increments_prediction_history(self):
        state = PrecisionState(prediction_history=5)
        updated = update_precision_state(state, [0.1, 0.1, 0.1])
        assert updated.prediction_history == 6

    def test_preserves_domain(self):
        state = PrecisionState(domain="test-domain")
        updated = update_precision_state(state, [0.1, 0.1, 0.1])
        assert updated.domain == "test-domain"


# ── Precision to Confidence ──────────────────────────────────────────────


class TestPrecisionToConfidence:
    def test_high_precision_high_confidence(self):
        conf = precision_to_confidence([5.0, 5.0, 5.0])
        assert conf > 0.8

    def test_low_precision_low_confidence(self):
        conf = precision_to_confidence([0.2, 0.2, 0.2])
        assert conf < 0.3

    def test_bounded_zero_to_one(self):
        assert 0.0 <= precision_to_confidence([0.1, 0.1, 0.1]) <= 1.0
        assert 0.0 <= precision_to_confidence([10.0, 10.0, 10.0]) <= 1.0

    def test_midpoint_precision(self):
        conf = precision_to_confidence([1.5, 1.5, 1.5])
        assert 0.4 < conf < 0.6  # Close to sigmoid midpoint


# ── Calibration ──────────────────────────────────────────────────────────


class TestCalibration:
    def test_correct_high_confidence_increases_hits(self):
        state = PrecisionState(calibration_hits=0, calibration_total=0)
        updated = check_calibration(state, predicted_confidence=0.8, was_useful=True)
        assert updated.calibration_hits == 1
        assert updated.calibration_total == 1

    def test_wrong_high_confidence_no_hit(self):
        state = PrecisionState(calibration_hits=0, calibration_total=0)
        updated = check_calibration(state, predicted_confidence=0.8, was_useful=False)
        assert updated.calibration_hits == 0
        assert updated.calibration_total == 1

    def test_low_confidence_not_tracked(self):
        state = PrecisionState(calibration_hits=0, calibration_total=0)
        updated = check_calibration(state, predicted_confidence=0.3, was_useful=True)
        assert updated.calibration_hits == 0  # Below threshold
        assert updated.calibration_total == 1

    def test_calibration_score_insufficient_data(self):
        state = PrecisionState(calibration_hits=2, calibration_total=3)
        assert calibration_score(state) == 0.5  # Not enough data

    def test_calibration_score_with_data(self):
        state = PrecisionState(calibration_hits=8, calibration_total=10)
        assert calibration_score(state) == pytest.approx(0.8)


# ── Integration: NE/Precision in Hierarchical Novelty ────────────────────


class TestPrecisionIntegration:
    def test_ne_modulates_novelty(self):
        """Higher NE should amplify prediction errors → higher free energy."""
        base_args = dict(
            content="def test_function():\n    pass",
            new_entity_names=["test_function"],
            known_entity_names=set(),
            recent_memories_features=[],
        )
        prec_state = PrecisionState(level_precisions=[1.0, 1.0, 1.0])

        result_low_ne = compute_hierarchical_novelty(
            **base_args,
            ne_level=0.5,
            precision_state=prec_state,
        )
        result_high_ne = compute_hierarchical_novelty(
            **base_args,
            ne_level=1.8,
            precision_state=prec_state,
        )
        assert result_high_ne.total_free_energy > result_low_ne.total_free_energy

    def test_without_precision_state_unchanged(self):
        """Without precision_state, NE/ACh still work via ACh modulation."""
        result = compute_hierarchical_novelty(
            content="test",
            new_entity_names=[],
            known_entity_names=set(),
            recent_memories_features=[],
            ne_level=1.5,
            precision_state=None,
        )
        assert result.total_free_energy >= 0

    def test_precision_state_evolves(self):
        """Full cycle: compute novelty → update precision → compute again."""
        prec = PrecisionState(level_precisions=[1.0, 1.0, 1.0])

        result = compute_hierarchical_novelty(
            content="test",
            new_entity_names=["new_thing"],
            known_entity_names=set(),
            recent_memories_features=[],
            precision_state=prec,
        )

        # Update precision with observed errors
        errors = [level.free_energy for level in result.levels]
        prec = update_precision_state(prec, errors)

        # Precision should have adapted
        assert prec.prediction_history == 1
