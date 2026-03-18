"""Tests for oscillatory_clock — theta/gamma/SWR phase-gating system."""

import pytest
from mcp_server.core.oscillatory_phases import (
    OscillatoryState,
    ThetaPhase,
    SWRState,
    classify_theta_phase,
    compute_encoding_strength,
    compute_retrieval_strength,
    compute_ach_from_phase,
    can_bind_item,
    gamma_binding_strength,
    should_generate_swr,
    compute_replay_priority,
)
from mcp_server.core.oscillatory_clock import (
    advance_theta,
    advance_gamma,
    begin_swr,
    step_swr,
    is_swr_active,
    modulate_encoding,
    modulate_retrieval,
    modulate_plasticity,
    state_to_dict,
    state_from_dict,
)


# ── Theta Phase Classification ────────────────────────────────────────────


class TestThetaPhase:
    def test_encoding_phase(self):
        assert classify_theta_phase(0.2) == ThetaPhase.ENCODING
        assert classify_theta_phase(0.3) == ThetaPhase.ENCODING

    def test_retrieval_phase(self):
        assert classify_theta_phase(0.7) == ThetaPhase.RETRIEVAL
        assert classify_theta_phase(0.8) == ThetaPhase.RETRIEVAL

    def test_transition_at_boundaries(self):
        assert classify_theta_phase(0.0) == ThetaPhase.TRANSITION
        assert classify_theta_phase(0.5) == ThetaPhase.TRANSITION

    def test_wraps_at_1(self):
        # Phase 1.2 should wrap to 0.2 (encoding)
        assert classify_theta_phase(1.2) == ThetaPhase.ENCODING

    def test_encoding_strength_peaks_at_quarter(self):
        peak = compute_encoding_strength(0.25)
        trough = compute_encoding_strength(0.75)
        assert peak > trough
        assert peak == pytest.approx(1.0, abs=0.01)
        assert trough == pytest.approx(0.3, abs=0.01)

    def test_retrieval_strength_peaks_at_three_quarter(self):
        peak = compute_retrieval_strength(0.75)
        trough = compute_retrieval_strength(0.25)
        assert peak > trough

    def test_encoding_retrieval_complementary(self):
        """Encoding and retrieval should sum to approximately constant."""
        for phase in [0.0, 0.1, 0.25, 0.5, 0.75, 0.9]:
            total = compute_encoding_strength(phase) + compute_retrieval_strength(phase)
            assert total == pytest.approx(1.3, abs=0.05)

    def test_ach_follows_encoding(self):
        """ACh should be high during encoding, low during retrieval."""
        ach_encoding = compute_ach_from_phase(0.25)
        ach_retrieval = compute_ach_from_phase(0.75)
        assert ach_encoding > ach_retrieval


# ── Gamma Binding ─────────────────────────────────────────────────────────


class TestGammaBinding:
    def test_can_bind_under_capacity(self):
        assert can_bind_item(0) is True
        assert can_bind_item(6) is True

    def test_cannot_bind_at_capacity(self):
        assert can_bind_item(7) is False
        assert can_bind_item(10) is False

    def test_binding_strength_u_shaped(self):
        """First and last positions should be strong (serial position effect)."""
        first = gamma_binding_strength(0)
        middle = gamma_binding_strength(3)
        last = gamma_binding_strength(6)
        assert first > middle
        assert last > middle

    def test_binding_strength_bounded(self):
        for pos in range(7):
            s = gamma_binding_strength(pos)
            assert 0.5 <= s <= 1.0


# ── Sharp-Wave Ripples ────────────────────────────────────────────────────


class TestSWR:
    def test_no_swr_during_refractory(self):
        assert should_generate_swr(20, 0.1) is False

    def test_no_swr_with_few_operations(self):
        assert should_generate_swr(1, 2.0) is False

    def test_swr_triggered_with_enough_activity(self):
        assert should_generate_swr(20, 2.0, accumulated_importance=5.0) is True

    def test_swr_respects_min_interval(self):
        assert should_generate_swr(20, 0.3, accumulated_importance=5.0) is False

    def test_replay_priority_moderate_heat(self):
        """Moderate heat memories should have highest replay priority."""
        hot = compute_replay_priority(0.9, 0.8, 0.5, 2, 10)
        moderate = compute_replay_priority(0.5, 0.8, 0.5, 2, 10)
        cold = compute_replay_priority(0.1, 0.8, 0.5, 2, 10)
        assert moderate > hot
        assert moderate > cold

    def test_replay_priority_importance_matters(self):
        high_imp = compute_replay_priority(0.5, 0.9, 0.5, 2, 10)
        low_imp = compute_replay_priority(0.5, 0.2, 0.5, 2, 10)
        assert high_imp > low_imp


# ── State Transitions ─────────────────────────────────────────────────────


class TestStateTransitions:
    def test_advance_theta_increments_phase(self):
        state = OscillatoryState()
        new_state = advance_theta(state, 5)
        assert new_state.theta_phase == pytest.approx(0.25)
        assert new_state.operations_since_swr == 5

    def test_advance_theta_wraps_at_cycle(self):
        state = OscillatoryState(theta_phase=0.9)
        new_state = advance_theta(state, 5)
        assert new_state.theta_phase < 0.9  # Wrapped
        assert new_state.theta_cycles_total > state.theta_cycles_total

    def test_advance_gamma_increments(self):
        state = OscillatoryState(gamma_count=2)
        new_state = advance_gamma(state)
        assert new_state.gamma_count == 3

    def test_swr_lifecycle(self):
        state = OscillatoryState()
        # Begin SWR
        state = begin_swr(state)
        assert is_swr_active(state) is True
        assert state.operations_since_swr == 0
        # Step through ripple
        for _ in range(5):
            state = step_swr(state)
        assert state.swr_state == SWRState.REFRACTORY.value
        # Step through refractory
        for _ in range(3):
            state = step_swr(state)
        assert state.swr_state == SWRState.QUIESCENT.value

    def test_ach_updates_with_phase(self):
        state = OscillatoryState()
        encoding_state = advance_theta(state, 5)  # phase ~0.25
        retrieval_state = advance_theta(state, 15)  # phase ~0.75
        assert encoding_state.ach_level > retrieval_state.ach_level


# ── Phase-Gated Modulation ────────────────────────────────────────────────


class TestModulation:
    def test_encoding_boosted_during_encoding_phase(self):
        state = OscillatoryState(theta_phase=0.25)  # Encoding peak
        modulated = modulate_encoding(1.0, state)
        assert modulated > 0.9

    def test_encoding_suppressed_during_retrieval_phase(self):
        state = OscillatoryState(theta_phase=0.75)  # Retrieval peak
        modulated = modulate_encoding(1.0, state)
        assert modulated < 0.5

    def test_encoding_suppressed_during_swr(self):
        state = OscillatoryState(theta_phase=0.25, swr_state="ripple")
        modulated = modulate_encoding(1.0, state)
        assert modulated < 0.5

    def test_retrieval_boosted_during_retrieval_phase(self):
        state = OscillatoryState(theta_phase=0.75)
        modulated = modulate_retrieval(1.0, state)
        assert modulated > 0.9

    def test_plasticity_boosted_during_swr(self):
        normal_state = OscillatoryState(theta_phase=0.25)
        swr_state = OscillatoryState(theta_phase=0.25, swr_state="ripple")
        normal = modulate_plasticity(1.0, normal_state)
        during_swr = modulate_plasticity(1.0, swr_state)
        assert during_swr > normal


# ── Serialization ─────────────────────────────────────────────────────────


class TestSerialization:
    def test_roundtrip(self):
        state = OscillatoryState(
            theta_phase=0.3,
            gamma_count=4,
            swr_state="ripple",
            theta_cycles_total=10,
            operations_since_swr=5,
        )
        d = state_to_dict(state)
        restored = state_from_dict(d)
        assert restored.theta_phase == state.theta_phase
        assert restored.gamma_count == state.gamma_count
        assert restored.swr_state == state.swr_state
        assert restored.theta_cycles_total == state.theta_cycles_total

    def test_from_empty_dict(self):
        state = state_from_dict({})
        assert state.theta_phase == 0.0
        assert state.swr_state == "quiescent"
