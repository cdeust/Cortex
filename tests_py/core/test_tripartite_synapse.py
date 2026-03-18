"""Tests for tripartite_synapse — astrocyte-mediated synaptic modulation."""

import pytest
from mcp_server.core.tripartite_synapse import (
    AstrocyteTerritory,
    compute_calcium_rise,
    compute_calcium_decay,
    classify_calcium_regime,
    compute_metabolic_rate,
    update_territory,
    territory_to_dict,
    territory_from_dict,
)
from mcp_server.core.tripartite_calcium import (
    propagate_calcium_wave,
    compute_ltp_modulation,
    compute_heterosynaptic_depression,
    apply_metabolic_modulation,
)


class TestCalciumDynamics:
    def test_rise_from_zero(self):
        ca = compute_calcium_rise(0.0, 3)
        assert ca > 0
        assert ca <= 1.0

    def test_rise_saturates(self):
        ca = compute_calcium_rise(0.9, 10)
        assert ca <= 1.0

    def test_no_rise_without_events(self):
        ca = compute_calcium_rise(0.5, 0)
        assert ca == 0.5

    def test_decay_reduces(self):
        ca = compute_calcium_decay(0.8, 2.0)
        assert ca < 0.8

    def test_no_decay_without_time(self):
        ca = compute_calcium_decay(0.8, 0.0)
        assert ca == 0.8

    def test_rise_then_decay_lifecycle(self):
        ca = 0.0
        ca = compute_calcium_rise(ca, 5)  # Activity
        assert ca > 0.3
        ca = compute_calcium_decay(ca, 10.0)  # Rest
        assert ca < 0.5  # Decayed but slow leak rate


class TestCalciumWave:
    def test_wave_propagates(self):
        neighbors = [0.0, 0.1, 0.0]
        updated = propagate_calcium_wave(0.8, neighbors)
        assert all(u >= n for u, n in zip(updated, neighbors))

    def test_no_wave_below_threshold(self):
        neighbors = [0.0, 0.1, 0.0]
        updated = propagate_calcium_wave(0.1, neighbors)
        assert updated == neighbors

    def test_wave_saturates(self):
        neighbors = [0.95]
        updated = propagate_calcium_wave(1.0, neighbors)
        assert updated[0] <= 1.0


class TestCalciumRegimes:
    def test_quiescent(self):
        assert classify_calcium_regime(0.1) == "quiescent"

    def test_facilitation(self):
        assert classify_calcium_regime(0.45) == "facilitation"

    def test_depression(self):
        assert classify_calcium_regime(0.8) == "depression"

    def test_ltp_facilitated_at_medium_ca(self):
        mod = compute_ltp_modulation(0.45)
        assert mod > 1.0  # D-serine boost

    def test_ltp_depressed_at_high_ca(self):
        mod = compute_ltp_modulation(0.9)
        assert mod < 1.0  # Glutamate depression

    def test_ltp_neutral_at_low_ca(self):
        mod = compute_ltp_modulation(0.1)
        assert mod == 1.0


class TestHeterosynapticDepression:
    def test_no_depression_below_threshold(self):
        adj = compute_heterosynaptic_depression(0.3, [0.5, 0.3, 0.8])
        assert all(a == 1.0 for a in adj)

    def test_cold_memories_depressed_more(self):
        adj = compute_heterosynaptic_depression(0.9, [0.8, 0.2])
        # Cold memory (0.2) should be depressed more than hot (0.8)
        assert adj[1] < adj[0]

    def test_depression_bounded(self):
        adj = compute_heterosynaptic_depression(1.0, [0.01, 0.01])
        assert all(a >= 0.5 for a in adj)


class TestMetabolicGating:
    def test_high_activity_boosts(self):
        rate = compute_metabolic_rate(20.0, 4.0)
        assert rate > 1.0

    def test_low_activity_starves(self):
        rate = compute_metabolic_rate(0.1, 10.0)
        assert rate < 1.0

    def test_baseline_at_normal_activity(self):
        rate = compute_metabolic_rate(4.0, 4.0)
        assert rate == pytest.approx(1.0, abs=0.2)

    def test_metabolic_slows_decay(self):
        # High metabolic rate should produce higher decay factor (slower decay)
        high_met = apply_metabolic_modulation(0.95, 1.5)
        low_met = apply_metabolic_modulation(0.95, 0.6)
        assert high_met > low_met

    def test_metabolic_modulation_bounded(self):
        factor = apply_metabolic_modulation(0.95, 0.1)
        assert 0.0 <= factor <= 1.0


class TestTerritoryUpdate:
    def test_activity_raises_calcium(self):
        t = AstrocyteTerritory(territory_id="t1")
        t2 = update_territory(t, synaptic_events=5, hours_elapsed=0.5)
        assert t2.calcium > 0

    def test_inactivity_decays_calcium(self):
        t = AstrocyteTerritory(territory_id="t1", calcium=0.8)
        t2 = update_territory(t, synaptic_events=0, hours_elapsed=10.0)
        assert t2.calcium < 0.8

    def test_metabolic_rate_updates(self):
        t = AstrocyteTerritory(territory_id="t1", total_activity=0.0)
        t2 = update_territory(t, synaptic_events=10, hours_elapsed=1.0)
        assert t2.metabolic_rate > 1.0

    def test_regime_flags_set(self):
        t = AstrocyteTerritory(territory_id="t1", calcium=0.0)
        # Enough events to push calcium into facilitation
        t2 = update_territory(t, synaptic_events=3, hours_elapsed=0.1)
        # Should be in facilitation or depression depending on Ca level
        assert t2.d_serine_active or t2.glutamate_active or t2.calcium < 0.3


class TestSerialization:
    def test_roundtrip(self):
        t = AstrocyteTerritory(
            territory_id="t1",
            domain="test",
            calcium=0.5,
            metabolic_rate=1.2,
            memory_ids=[1, 2, 3],
            total_activity=15.0,
            d_serine_active=True,
        )
        d = territory_to_dict(t)
        restored = territory_from_dict(d)
        assert restored.territory_id == "t1"
        assert restored.calcium == 0.5
        assert restored.memory_ids == [1, 2, 3]
        assert restored.d_serine_active is True

    def test_from_empty_dict(self):
        t = territory_from_dict({})
        assert t.calcium == 0.0
        assert t.metabolic_rate == 1.0
