"""Unit tests for the B3 cerebellar forward-model primitive (forward_model.py).

Covers the two primitive operations (predict / correction), the trajectory
replay (run_forward_model / prediction_error), the deadband, the vector→scalar
reduction, and edge cases (empty / single-point trajectories, gain bounds).
"""

from __future__ import annotations

import math

from mcp_server.core.forward_model import (
    CORRECTION_GAIN,
    ERROR_DEADBAND,
    ForwardModelState,
    correction,
    forward_model_state_as_dict,
    predict,
    prediction_error,
    run_forward_model,
    scalar_of,
)


class TestPredict:
    def test_predict_returns_estimate(self):
        st = ForwardModelState(estimate=0.42)
        assert predict(st) == 0.42


class TestCorrection:
    def test_signed_error(self):
        # actual above prediction -> positive error
        error, corrected = correction(0.2, 0.8)
        assert error == 0.8 - 0.2
        # corrected steps toward actual by the default gain
        assert corrected == 0.2 + CORRECTION_GAIN * (0.8 - 0.2)

    def test_negative_error(self):
        error, corrected = correction(0.8, 0.2)
        assert error < 0
        assert corrected < 0.8  # stepped down toward actual

    def test_deadband_leaves_estimate_unchanged(self):
        # residual within the deadband: error reported, estimate frozen
        error, corrected = correction(0.50, 0.50 + ERROR_DEADBAND * 0.5)
        assert corrected == 0.50
        assert abs(error) <= ERROR_DEADBAND

    def test_gain_zero_freezes_estimate(self):
        error, corrected = correction(0.2, 0.9, gain=0.0)
        assert corrected == 0.2  # no correction folded in
        assert error == 0.9 - 0.2  # but error still reported

    def test_gain_one_jumps_to_actual(self):
        error, corrected = correction(0.2, 0.9, gain=1.0)
        assert math.isclose(corrected, 0.9)

    def test_gain_is_clamped(self):
        # out-of-range gain is clamped to [0,1]; >1 behaves like 1
        _, corrected_hi = correction(0.2, 0.9, gain=5.0)
        assert math.isclose(corrected_hi, 0.9)
        _, corrected_lo = correction(0.2, 0.9, gain=-5.0)
        assert corrected_lo == 0.2


class TestRunForwardModel:
    def test_empty_trajectory(self):
        st = run_forward_model([])
        assert st.estimate == 0.0
        assert st.error == 0.0
        assert st.n_updates == 0

    def test_single_point_seeds_estimate_no_error(self):
        st = run_forward_model([0.7])
        assert st.estimate == 0.7
        assert st.error == 0.0
        assert st.n_updates == 0  # nothing to predict yet

    def test_constant_trajectory_has_zero_final_error(self):
        # a perfectly predictable signal produces no residual at the last step
        st = run_forward_model([0.5, 0.5, 0.5, 0.5])
        assert abs(st.error) <= ERROR_DEADBAND
        assert st.n_updates == 3

    def test_estimate_tracks_toward_trend(self):
        # rising signal -> estimate rises but lags the latest observation
        st = run_forward_model([0.0, 0.2, 0.4, 0.6])
        assert 0.0 < st.estimate < 0.6

    def test_jump_produces_large_error(self):
        st = run_forward_model([0.1, 0.1, 0.1, 0.9])
        assert st.error > ERROR_DEADBAND


class TestPredictionError:
    def test_empty_history_zero(self):
        assert prediction_error([], 0.9) == 0.0

    def test_expected_value_deadbanded_to_zero(self):
        # actual matches what a flat history predicts -> within deadband -> 0.0
        assert prediction_error([0.5, 0.5, 0.5], 0.5) == 0.0

    def test_surprising_value_positive(self):
        err = prediction_error([0.1, 0.1, 0.1], 0.9)
        assert err > 0

    def test_undershoot_negative(self):
        err = prediction_error([0.9, 0.9, 0.9], 0.1)
        assert err < 0


class TestScalarOf:
    def test_empty(self):
        assert scalar_of({}) == 0.0

    def test_mean_activation(self):
        assert math.isclose(scalar_of({"a": 0.2, "b": 0.4, "c": 0.6}), 0.4)

    def test_reduces_feature_vector_for_the_model(self):
        # a feature dict collapses to its mean before feeding the 1-D model
        feats = [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}, {"x": 0.9, "y": 0.9}]
        traj = [scalar_of(f) for f in feats[:-1]]
        err = prediction_error(traj, scalar_of(feats[-1]))
        assert err > 0


class TestForwardModelStateAsDict:
    """issue #282: dataclass mutation blindspot — direct coverage of the
    extracted free function (was ForwardModelState.as_dict)."""

    def test_rounds_all_fields(self):
        # error and corrected each carry a 7th-decimal digit so round(x, 6)
        # vs round(x, 7) and vs round(x, None) (int truncation) are all
        # observably different (issue #282 mutation-testing gap: the
        # original -0.0000001 / 0.5 values rounded identically at every
        # precision — -0.0000001 rounds to 0.0 whether ndigits is 6 or
        # None, and 0.5 has no 7th digit to lose).
        state = ForwardModelState(
            estimate=0.123456789, error=-0.1234567, corrected=0.5123456, n_updates=3
        )
        d = forward_model_state_as_dict(state)
        assert d == {
            "estimate": round(0.123456789, 6),
            "error": round(-0.1234567, 6),
            "corrected": round(0.5123456, 6),
            "n_updates": 3,
        }
