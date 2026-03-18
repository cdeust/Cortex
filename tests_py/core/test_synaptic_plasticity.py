"""Tests for mcp_server.core.synaptic_plasticity — LTP/LTD + STDP."""

from mcp_server.core.synaptic_plasticity import (
    compute_ltp,
    compute_ltd,
    update_bcm_threshold,
    apply_hebbian_update,
    compute_stdp_update,
    apply_stdp_batch,
)


class TestLTP:
    def test_co_activation_increases_weight(self):
        new_w = compute_ltp(0.5, co_activation=1.0, post_activity=0.8, theta=0.5)
        assert new_w > 0.5

    def test_below_threshold_no_change(self):
        new_w = compute_ltp(0.5, co_activation=1.0, post_activity=0.3, theta=0.5)
        assert new_w == 0.5

    def test_max_weight_capped(self):
        new_w = compute_ltp(
            1.9, co_activation=1.0, post_activity=1.0, theta=0.0, ltp_rate=0.5
        )
        assert new_w <= 2.0

    def test_zero_co_activation_no_change(self):
        new_w = compute_ltp(0.5, co_activation=0.0, post_activity=1.0, theta=0.0)
        assert new_w == 0.5

    def test_stronger_co_activation_bigger_boost(self):
        w1 = compute_ltp(0.5, co_activation=0.3, post_activity=0.8, theta=0.5)
        w2 = compute_ltp(0.5, co_activation=1.0, post_activity=0.8, theta=0.5)
        assert w2 > w1


class TestLTD:
    def test_inactive_edge_decays(self):
        new_w = compute_ltd(0.5, time_since_co_access_hours=48)
        assert new_w < 0.5

    def test_min_weight_floor(self):
        new_w = compute_ltd(0.02, time_since_co_access_hours=1000)
        assert new_w >= 0.01

    def test_zero_time_no_change(self):
        assert compute_ltd(0.5, 0) == 0.5

    def test_longer_inactivity_more_decay(self):
        w1 = compute_ltd(0.5, 24)
        w2 = compute_ltd(0.5, 168)
        assert w2 < w1


class TestBCMThreshold:
    def test_high_activity_raises_threshold(self):
        theta = update_bcm_threshold(0.5, entity_activity=0.9)
        assert theta > 0.5

    def test_low_activity_lowers_threshold(self):
        theta = update_bcm_threshold(0.5, entity_activity=0.1)
        assert theta < 0.5

    def test_ema_decay(self):
        theta = update_bcm_threshold(0.5, entity_activity=0.5, decay=0.9)
        # Should converge toward 0.5^2 = 0.25 with decay
        assert theta < 0.5


class TestHebbianBatch:
    def test_co_accessed_edges_strengthen(self):
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        results = apply_hebbian_update(
            edges,
            co_accessed_pairs={(1, 2)},
            entity_activities={1: 0.8, 2: 0.8},
            entity_thresholds={1: 0.3, 2: 0.3},
        )
        assert results[0]["action"] == "ltp"
        assert results[0]["weight"] > 0.5

    def test_inactive_edges_weaken(self):
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        results = apply_hebbian_update(
            edges,
            co_accessed_pairs=set(),
            entity_activities={1: 0.5, 2: 0.5},
            entity_thresholds={1: 0.5, 2: 0.5},
            hours_since_last_update=48,
        )
        assert results[0]["action"] == "ltd"
        assert results[0]["weight"] < 0.5

    def test_pair_normalized_to_min_max(self):
        """Edges are normalized to (min, max) — callers should do the same."""
        edges = [{"source_entity_id": 3, "target_entity_id": 1, "weight": 0.5}]
        # Both (1,3) and (3,1) should match when normalized
        r1 = apply_hebbian_update(edges, {(1, 3)}, {1: 0.8, 3: 0.8}, {1: 0.3, 3: 0.3})
        assert r1[0]["action"] == "ltp"
        assert r1[0]["weight"] > 0.5


class TestSTDP:
    def test_causal_order_strengthens(self):
        # Source appeared 2 hours before target → LTP
        new_w = compute_stdp_update(0.5, delta_t_hours=2.0)
        assert new_w > 0.5

    def test_anti_causal_weakens(self):
        # Target appeared before source → LTD
        new_w = compute_stdp_update(0.5, delta_t_hours=-2.0)
        assert new_w < 0.5

    def test_simultaneous_no_change(self):
        assert compute_stdp_update(0.5, delta_t_hours=0.0) == 0.5

    def test_bounded(self):
        assert compute_stdp_update(0.01, delta_t_hours=-100) >= 0.01
        assert compute_stdp_update(1.9, delta_t_hours=0.1) <= 2.0

    def test_closer_timing_stronger_effect(self):
        close = compute_stdp_update(0.5, delta_t_hours=1.0)
        far = compute_stdp_update(0.5, delta_t_hours=48.0)
        assert close > far  # Closer timing = stronger LTP

    def test_exponential_decay(self):
        w1 = compute_stdp_update(0.5, delta_t_hours=1.0)
        w2 = compute_stdp_update(0.5, delta_t_hours=24.0)
        w3 = compute_stdp_update(0.5, delta_t_hours=72.0)
        assert w1 > w2 > w3  # Monotonic decay


class TestSTDPBatch:
    def test_batch_processing(self):
        pairs = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "current_weight": 0.5,
                "delta_t_hours": 2.0,
            },
            {
                "source_entity_id": 3,
                "target_entity_id": 4,
                "current_weight": 0.5,
                "delta_t_hours": -3.0,
            },
        ]
        results = apply_stdp_batch(pairs)
        assert len(results) == 2
        assert results[0]["direction"] == "causal"
        assert results[0]["new_weight"] > 0.5
        assert results[1]["direction"] == "anti-causal"
        assert results[1]["new_weight"] < 0.5

    def test_empty_batch(self):
        assert apply_stdp_batch([]) == []
