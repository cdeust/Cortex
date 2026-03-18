"""Tests for stochastic synaptic transmission in synaptic_plasticity.py.

Covers: release probability, facilitation, depression, noise injection,
phase-gated plasticity, and the full stochastic Hebbian update.
"""

import random

import pytest

from mcp_server.core.synaptic_plasticity import (
    SynapticState,
    compute_effective_release_probability,
    stochastic_transmit,
    update_short_term_dynamics,
    compute_noisy_weight_update,
    phase_modulate_plasticity,
    apply_stochastic_hebbian_update,
)


# ── Release Probability ──────────────────────────────────────────────────


class TestEffectiveReleaseProbability:
    def test_base_only(self):
        state = SynapticState(release_probability=0.5)
        assert compute_effective_release_probability(state) == 0.5

    def test_facilitation_increases_p(self):
        state = SynapticState(release_probability=0.5, facilitation=0.2)
        assert compute_effective_release_probability(state) == pytest.approx(0.7)

    def test_depression_decreases_p(self):
        state = SynapticState(release_probability=0.5, depression=0.3)
        assert compute_effective_release_probability(state) == pytest.approx(0.2)

    def test_clamped_high(self):
        state = SynapticState(release_probability=0.9, facilitation=0.5)
        assert compute_effective_release_probability(state) == 0.95

    def test_clamped_low(self):
        state = SynapticState(release_probability=0.1, depression=0.8)
        assert compute_effective_release_probability(state) == 0.05

    def test_facilitation_and_depression_cancel(self):
        state = SynapticState(release_probability=0.5, facilitation=0.3, depression=0.3)
        assert compute_effective_release_probability(state) == pytest.approx(0.5)


# ── Stochastic Transmission ─────────────────────────────────────────────


class TestStochasticTransmit:
    def test_high_probability_mostly_transmits(self):
        state = SynapticState(release_probability=0.95)
        rng = random.Random(42)
        transmissions = sum(stochastic_transmit(state, rng=rng) for _ in range(100))
        assert transmissions > 80

    def test_low_probability_mostly_blocks(self):
        state = SynapticState(release_probability=0.05)
        rng = random.Random(42)
        transmissions = sum(stochastic_transmit(state, rng=rng) for _ in range(100))
        assert transmissions < 20

    def test_deterministic_with_fixed_rng(self):
        state = SynapticState(release_probability=0.5)
        rng1 = random.Random(123)
        rng2 = random.Random(123)
        results1 = [stochastic_transmit(state, rng=rng1) for _ in range(10)]
        results2 = [stochastic_transmit(state, rng=rng2) for _ in range(10)]
        assert results1 == results2


# ── Short-Term Dynamics ──────────────────────────────────────────────────


class TestShortTermDynamics:
    def test_access_increases_facilitation(self):
        state = SynapticState(hours_since_last_access=2.0)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.facilitation > 0
        assert updated.access_count == 1

    def test_rapid_access_triggers_depression(self):
        state = SynapticState(hours_since_last_access=0.1)  # Very recent
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.depression > 0

    def test_slow_access_no_depression(self):
        state = SynapticState(hours_since_last_access=2.0)  # Not rapid
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.depression == 0.0

    def test_facilitation_decays_over_time(self):
        state = SynapticState(facilitation=0.5, hours_since_last_access=1.0)
        updated = update_short_term_dynamics(state, hours_elapsed=5.0, is_access=False)
        assert updated.facilitation < 0.5

    def test_depression_decays_over_time(self):
        state = SynapticState(depression=0.5, hours_since_last_access=0.1)
        updated = update_short_term_dynamics(state, hours_elapsed=5.0, is_access=False)
        assert updated.depression < 0.5

    def test_no_elapsed_no_decay(self):
        state = SynapticState(facilitation=0.5, depression=0.3)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=False)
        assert updated.facilitation == 0.5
        assert updated.depression == 0.3

    def test_access_resets_hours_since(self):
        state = SynapticState(hours_since_last_access=10.0)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.hours_since_last_access == 0.0

    def test_facilitation_capped_at_one(self):
        state = SynapticState(facilitation=0.95)
        updated = update_short_term_dynamics(state, hours_elapsed=0.0, is_access=True)
        assert updated.facilitation <= 1.0


# ── Noise Injection ──────────────────────────────────────────────────────


class TestNoisyWeightUpdate:
    def test_noise_adds_variance(self):
        rng = random.Random(42)
        deltas = [
            compute_noisy_weight_update(0.05, access_count=1, rng=rng)
            for _ in range(100)
        ]
        # Should have variance around 0.05
        assert not all(d == 0.05 for d in deltas)
        assert abs(sum(deltas) / len(deltas) - 0.05) < 0.02

    def test_high_access_count_less_noise(self):
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        low_evidence = [
            compute_noisy_weight_update(0.05, access_count=1, rng=rng1)
            for _ in range(200)
        ]
        high_evidence = [
            compute_noisy_weight_update(0.05, access_count=100, rng=rng2)
            for _ in range(200)
        ]
        # Variance of high evidence should be much smaller
        var_low = sum((d - 0.05) ** 2 for d in low_evidence) / len(low_evidence)
        var_high = sum((d - 0.05) ** 2 for d in high_evidence) / len(high_evidence)
        assert var_high < var_low

    def test_zero_access_count_uses_full_noise(self):
        rng = random.Random(42)
        d = compute_noisy_weight_update(0.0, access_count=0, rng=rng)
        assert d != 0.0  # Should have noise added


# ── Phase-Gated Plasticity ───────────────────────────────────────────────


class TestPhaseModulation:
    def test_ltp_strongest_at_encoding_peak(self):
        # Encoding peak at theta_phase=0.25
        ltp_encoding = phase_modulate_plasticity(0.05, theta_phase=0.25, is_ltp=True)
        ltp_retrieval = phase_modulate_plasticity(0.05, theta_phase=0.75, is_ltp=True)
        assert ltp_encoding > ltp_retrieval

    def test_ltd_strongest_at_retrieval_peak(self):
        # LTD should be amplified during retrieval phase
        ltd_retrieval = phase_modulate_plasticity(-0.02, theta_phase=0.75, is_ltp=False)
        ltd_encoding = phase_modulate_plasticity(-0.02, theta_phase=0.25, is_ltp=False)
        # More negative = stronger depression
        assert ltd_retrieval < ltd_encoding

    def test_encoding_peak_gives_max_ltp(self):
        result = phase_modulate_plasticity(1.0, theta_phase=0.25, is_ltp=True)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_retrieval_peak_gives_min_ltp(self):
        result = phase_modulate_plasticity(1.0, theta_phase=0.75, is_ltp=True)
        assert result == pytest.approx(0.3, abs=0.01)

    def test_never_fully_zero(self):
        # Even at worst phase, some plasticity occurs
        result = phase_modulate_plasticity(0.05, theta_phase=0.75, is_ltp=True)
        assert result > 0


# ── Stochastic Hebbian Update ────────────────────────────────────────────


class TestStochasticHebbianUpdate:
    def test_co_accessed_may_be_blocked(self):
        """With low release probability, some LTP attempts should be blocked."""
        edges = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.5,
                "release_probability": 0.1,
            }
        ]
        rng = random.Random(42)
        blocked_count = 0
        for _ in range(50):
            rng_copy = random.Random(rng.randint(0, 10**9))
            results = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                rng=rng_copy,
            )
            if results[0]["action"] == "blocked":
                blocked_count += 1
        assert blocked_count > 10  # Should block frequently with p=0.1

    def test_high_release_probability_mostly_succeeds(self):
        edges = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.5,
                "release_probability": 0.95,
            }
        ]
        rng = random.Random(42)
        ltp_count = 0
        for _ in range(50):
            rng_copy = random.Random(rng.randint(0, 10**9))
            results = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                rng=rng_copy,
            )
            if results[0]["action"] == "ltp":
                ltp_count += 1
        assert ltp_count > 30

    def test_returns_updated_synaptic_state(self):
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        rng = random.Random(42)
        results = apply_stochastic_hebbian_update(
            edges,
            co_accessed_pairs={(1, 2)},
            entity_activities={1: 0.8, 2: 0.8},
            entity_thresholds={1: 0.3, 2: 0.3},
            rng=rng,
        )
        r = results[0]
        assert "release_probability" in r
        assert "facilitation" in r
        assert "depression" in r
        assert "access_count" in r
        assert r["access_count"] == 1

    def test_phase_gating_modulates_ltp(self):
        """LTP during encoding phase should be stronger than retrieval."""
        edges = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.5,
                "release_probability": 0.99,
            }
        ]
        random.Random(42)
        random.Random(42)

        # Many trials to average out noise
        enc_deltas = []
        ret_deltas = []
        for i in range(100):
            r_enc = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                theta_phase=0.25,  # Encoding peak
                rng=random.Random(i),
            )
            r_ret = apply_stochastic_hebbian_update(
                edges,
                co_accessed_pairs={(1, 2)},
                entity_activities={1: 0.8, 2: 0.8},
                entity_thresholds={1: 0.3, 2: 0.3},
                theta_phase=0.75,  # Retrieval peak
                rng=random.Random(i),
            )
            enc_deltas.append(r_enc[0]["delta"])
            ret_deltas.append(r_ret[0]["delta"])

        avg_enc = sum(enc_deltas) / len(enc_deltas)
        avg_ret = sum(ret_deltas) / len(ret_deltas)
        assert avg_enc > avg_ret  # Encoding phase → stronger LTP

    def test_ltd_still_works(self):
        edges = [{"source_entity_id": 1, "target_entity_id": 2, "weight": 0.5}]
        results = apply_stochastic_hebbian_update(
            edges,
            co_accessed_pairs=set(),
            entity_activities={1: 0.5, 2: 0.5},
            entity_thresholds={1: 0.5, 2: 0.5},
            hours_since_last_update=48,
        )
        assert results[0]["action"] == "ltd"
        assert results[0]["weight"] < 0.5

    def test_empty_edges(self):
        results = apply_stochastic_hebbian_update(
            [],
            co_accessed_pairs=set(),
            entity_activities={},
            entity_thresholds={},
        )
        assert results == []
