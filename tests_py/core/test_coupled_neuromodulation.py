"""Tests for coupled_neuromodulation — cross-channel modulatory cascade."""

import pytest
from mcp_server.core.coupled_neuromodulation import (
    NeuromodulatoryState,
    OperationSignals,
    compute_dopamine_rpe,
    compute_norepinephrine_arousal,
    compute_serotonin_exploration,
    apply_cross_coupling,
    update_state,
    modulate_ltp_rate,
    modulate_precision_gain,
    modulate_write_gate_threshold,
    modulate_spreading_breadth,
    compute_cascade_gate,
    compute_composite_modulation,
    state_to_dict,
    state_from_dict,
)


class TestDopamine:
    def test_positive_rpe_from_success(self):
        da, _ = compute_dopamine_rpe(True, False, 0.5, 0.5)
        assert da > 1.0  # Positive RPE

    def test_negative_rpe_from_failure(self):
        da, _ = compute_dopamine_rpe(False, True, 0.5, 0.5)
        assert da < 1.0  # Negative RPE

    def test_neutral_rpe(self):
        da, _ = compute_dopamine_rpe(False, False, 0.5, 0.5)
        assert da == pytest.approx(1.0, abs=0.2)

    def test_baseline_adapts(self):
        _, baseline1 = compute_dopamine_rpe(True, False, 0.8, 0.3)
        assert baseline1 > 0.3  # Baseline moves toward actual reward

    def test_da_bounded(self):
        da, _ = compute_dopamine_rpe(True, False, 1.0, 0.0)
        assert 0.3 <= da <= 2.0


class TestNorepinephrine:
    def test_error_raises_ne(self):
        ne, _ = compute_norepinephrine_arousal(True, 1.0, 0.0)
        assert ne > 1.0

    def test_no_error_relaxes_ne(self):
        ne, _ = compute_norepinephrine_arousal(False, 1.5, 0.0)
        assert ne < 1.5

    def test_habituation_dampens_response(self):
        ne_fresh, _ = compute_norepinephrine_arousal(True, 1.0, 0.0)
        ne_habituated, _ = compute_norepinephrine_arousal(True, 1.0, 0.7)
        assert ne_fresh > ne_habituated

    def test_habituation_decays(self):
        _, adapt = compute_norepinephrine_arousal(False, 1.0, 0.5)
        assert adapt < 0.5


class TestSerotonin:
    def test_high_novelty_explores(self):
        ser = compute_serotonin_exploration(0.0, 5, 5, 1.0)
        assert ser > 1.0

    def test_high_schema_exploits(self):
        ser = compute_serotonin_exploration(0.9, 0, 5, 1.0)
        assert ser < 1.0


class TestCrossCoupling:
    def test_success_dampens_arousal(self):
        da, ne, ach, ser = apply_cross_coupling(1.8, 1.5, 1.0, 1.0)
        assert ne < 1.5  # DA dampens NE

    def test_arousal_boosts_encoding(self):
        da, ne, ach, ser = apply_cross_coupling(1.0, 1.8, 1.0, 1.0)
        assert ach > 1.0  # NE boosts ACh

    def test_all_bounded(self):
        da, ne, ach, ser = apply_cross_coupling(2.0, 2.0, 2.0, 2.0)
        for v in [da, ne, ach, ser]:
            assert 0.3 <= v <= 2.0


class TestStateUpdate:
    def test_state_evolves(self):
        state = NeuromodulatoryState()
        signals = OperationSignals(error_resolved=True, memory_importance=0.8)
        new = update_state(state, signals)
        assert new.dopamine != state.dopamine  # Should have changed

    def test_multiple_updates_converge(self):
        state = NeuromodulatoryState()
        for _ in range(20):
            state = update_state(state, OperationSignals())
        # All channels should be near baseline
        assert abs(state.dopamine - 1.0) < 0.3
        assert abs(state.norepinephrine - 1.0) < 0.3


class TestDownstreamModulation:
    def test_high_da_boosts_ltp(self):
        assert modulate_ltp_rate(0.05, 1.5) > 0.05

    def test_low_da_weakens_ltp(self):
        assert modulate_ltp_rate(0.05, 0.5) < 0.05

    def test_high_ne_boosts_precision(self):
        assert modulate_precision_gain(1.0, 1.5) > 1.0

    def test_high_ne_lowers_gate(self):
        assert modulate_write_gate_threshold(0.4, 1.5) < 0.4

    def test_high_ser_broadens_spread(self):
        assert modulate_spreading_breadth(3, 1.5) >= 3

    def test_low_ser_narrows_spread(self):
        assert modulate_spreading_breadth(3, 0.5) <= 3

    def test_cascade_gate_opens_with_high_da(self):
        assert compute_cascade_gate(1.5, 0.8) is True

    def test_cascade_gate_closed_with_low_da(self):
        assert compute_cascade_gate(0.5, 0.3) is False


class TestComposite:
    def test_composite_has_all_channels(self):
        state = NeuromodulatoryState(dopamine=1.2, norepinephrine=1.1)
        comp = compute_composite_modulation(state)
        assert "dopamine" in comp
        assert "heat_modulation" in comp
        assert "cascade_gate" in comp


class TestSerialization:
    def test_roundtrip(self):
        state = NeuromodulatoryState(dopamine=1.3, ne_adaptation=0.4)
        d = state_to_dict(state)
        restored = state_from_dict(d)
        assert restored.dopamine == state.dopamine
        assert restored.ne_adaptation == state.ne_adaptation
