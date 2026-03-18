"""Tests for mcp_server.core.engram — competitive slot allocation."""

from datetime import datetime, timezone, timedelta

from mcp_server.core.engram import (
    compute_decayed_excitability,
    find_best_slot,
    compute_boost,
    compute_lateral_inhibition,
    compute_slot_statistics,
)


class TestComputeDecayedExcitability:
    def test_recent_activation(self):
        now = datetime.now(timezone.utc).isoformat()
        result = compute_decayed_excitability(1.0, now, half_life_hours=6.0)
        # Very recent → almost no decay
        assert result > 0.95

    def test_one_half_life(self):
        six_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        result = compute_decayed_excitability(1.0, six_hours_ago, half_life_hours=6.0)
        assert abs(result - 0.5) < 0.05

    def test_no_activation(self):
        assert compute_decayed_excitability(0.5, None) == 0.0

    def test_zero_excitability(self):
        now = datetime.now(timezone.utc).isoformat()
        assert compute_decayed_excitability(0.0, now) == 0.0

    def test_invalid_timestamp(self):
        assert compute_decayed_excitability(0.5, "not-a-date") == 0.0

    def test_long_decay(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        result = compute_decayed_excitability(1.0, old, half_life_hours=6.0)
        assert result < 0.01


class TestFindBestSlot:
    def test_finds_most_excitable(self):
        recent = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        slots = [
            {"slot_index": 0, "excitability": 0.3, "last_activated": old},
            {"slot_index": 1, "excitability": 0.9, "last_activated": recent},
            {"slot_index": 2, "excitability": 0.5, "last_activated": old},
        ]
        best_slot, best_exc = find_best_slot(slots)
        assert best_slot == 1
        assert best_exc > 0.5

    def test_empty_slots(self):
        slot, exc = find_best_slot([])
        assert slot == 0
        assert exc == -1.0

    def test_all_decayed(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
        slots = [
            {"slot_index": 0, "excitability": 0.5, "last_activated": old},
            {"slot_index": 1, "excitability": 0.5, "last_activated": old},
        ]
        slot, exc = find_best_slot(slots)
        assert exc < 0.01


class TestComputeBoost:
    def test_basic_boost(self):
        assert compute_boost(0.3, 0.5) == 0.8

    def test_cap_at_one(self):
        assert compute_boost(0.8, 0.5) == 1.0

    def test_zero_boost(self):
        assert compute_boost(0.5, 0.0) == 0.5


class TestComputeLateralInhibition:
    def test_inhibits_neighbors(self):
        excitabilities = {0: 0.5, 1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5}
        updates = compute_lateral_inhibition(
            activated_slot=2,
            num_slots=5,
            all_excitabilities=excitabilities,
            inhibition_factor=0.25,
            inhibition_radius=2,
        )
        assert 0 in updates  # 2-2=0
        assert 1 in updates  # 2-1=1
        assert 3 in updates  # 2+1=3
        assert 4 in updates  # 2+2=4
        assert 2 not in updates  # Self not inhibited
        assert all(v < 0.5 for v in updates.values())

    def test_boundary_slots(self):
        excitabilities = {0: 0.5, 1: 0.5, 2: 0.5}
        updates = compute_lateral_inhibition(
            activated_slot=0,
            num_slots=3,
            all_excitabilities=excitabilities,
            inhibition_factor=0.25,
            inhibition_radius=2,
        )
        # Only positive indices
        assert all(idx >= 0 for idx in updates)

    def test_floor_at_zero(self):
        excitabilities = {0: 0.1, 1: 0.1}
        updates = compute_lateral_inhibition(
            activated_slot=0,
            num_slots=2,
            all_excitabilities=excitabilities,
            inhibition_factor=0.5,
        )
        assert updates.get(1, 0) == 0.0


class TestComputeSlotStatistics:
    def test_basic_stats(self):
        recent = datetime.now(timezone.utc).isoformat()
        slots = [
            {"slot_index": 0, "excitability": 0.8, "last_activated": recent},
            {"slot_index": 1, "excitability": 0.4, "last_activated": recent},
            {"slot_index": 2, "excitability": 0.2, "last_activated": recent},
        ]
        occupancy = {0: 3, 1: 1}
        stats = compute_slot_statistics(slots, occupancy)
        assert stats["total_slots"] == 3
        assert stats["occupied_slots"] == 2
        assert stats["avg_excitability"] > 0
        assert stats["max_excitability"] > 0

    def test_empty_slots(self):
        stats = compute_slot_statistics([], {})
        assert stats["total_slots"] == 0
        assert stats["avg_excitability"] == 0.0
