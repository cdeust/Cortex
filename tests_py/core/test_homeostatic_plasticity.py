"""Tests for homeostatic_plasticity — network stability mechanisms."""

from mcp_server.core.homeostatic_plasticity import (
    compute_scaling_factor,
    apply_synaptic_scaling,
    compute_bcm_threshold,
    compute_ltp_ltd_modulation,
    compute_excitability_adjustment,
    apply_excitability_bounds,
)
from mcp_server.core.homeostatic_health import compute_distribution_health


class TestSynapticScaling:
    def test_neutral_at_target(self):
        factor = compute_scaling_factor(0.4, target_heat=0.4)
        assert factor == 1.0

    def test_scales_down_when_too_hot(self):
        factor = compute_scaling_factor(0.7, target_heat=0.4)
        assert factor < 1.0

    def test_scales_up_when_too_cold(self):
        factor = compute_scaling_factor(0.1, target_heat=0.4)
        assert factor > 1.0

    def test_gentle_adjustment(self):
        """Scaling should be gentle, not dramatic."""
        factor = compute_scaling_factor(0.8, target_heat=0.4)
        assert factor > 0.9  # Less than 10% adjustment

    def test_apply_preserves_ordering(self):
        heats = [0.2, 0.5, 0.8]
        scaled = apply_synaptic_scaling(heats, 0.9)
        assert scaled[0] < scaled[1] < scaled[2]

    def test_apply_clamps_to_bounds(self):
        heats = [0.95, 0.01]
        scaled = apply_synaptic_scaling(heats, 1.2)
        assert all(0.0 <= h <= 1.0 for h in scaled)


class TestBCMThreshold:
    def test_threshold_tracks_activity(self):
        """High recent activity should raise the threshold."""
        high_activity = [0.8, 0.9, 0.7, 0.85]
        low_activity = [0.1, 0.2, 0.15, 0.1]
        theta_high = compute_bcm_threshold(high_activity, current_threshold=0.5)
        theta_low = compute_bcm_threshold(low_activity, current_threshold=0.5)
        assert theta_high > theta_low

    def test_threshold_stable_without_input(self):
        theta = compute_bcm_threshold([], current_threshold=0.5)
        assert theta == 0.5

    def test_ema_converges(self):
        """Repeated high activity should push threshold toward high."""
        theta = 0.5
        for _ in range(20):
            theta = compute_bcm_threshold([0.9, 0.9, 0.9], theta)
        assert theta > 0.69  # Converges toward 0.81 (0.9^2) but EMA is slow

    def test_ltp_boosted_above_threshold(self):
        ltp, ltd = compute_ltp_ltd_modulation(0.8, bcm_threshold=0.4)
        assert ltp > 1.0
        assert ltd < 1.0

    def test_ltd_boosted_below_threshold(self):
        ltp, ltd = compute_ltp_ltd_modulation(0.2, bcm_threshold=0.6)
        assert ltd > 1.0
        assert ltp < 1.0

    def test_modulation_bounded(self):
        ltp, ltd = compute_ltp_ltd_modulation(1.0, bcm_threshold=0.0)
        assert 0.0 <= ltp <= 2.0
        assert 0.0 <= ltd <= 2.0


class TestExcitabilityRegulation:
    def test_boosts_when_too_few_active(self):
        excitabilities = [0.1] * 10  # All low
        adj = compute_excitability_adjustment(excitabilities)
        assert adj > 0  # Should boost

    def test_dampens_when_too_many_active(self):
        excitabilities = [0.9] * 10  # All high
        adj = compute_excitability_adjustment(excitabilities)
        assert adj < 0  # Should dampen

    def test_neutral_at_target(self):
        # 3 out of 10 active = 30% = target
        excitabilities = [0.7, 0.8, 0.9] + [0.1] * 7
        adj = compute_excitability_adjustment(excitabilities)
        assert abs(adj) < 0.05

    def test_bounds_clamp(self):
        result = apply_excitability_bounds(0.05, adjustment=-0.1)
        assert result >= 0.1
        result = apply_excitability_bounds(0.95, adjustment=0.1)
        assert result <= 0.9


class TestDistributionHealth:
    def test_healthy_distribution(self):
        values = [0.2, 0.3, 0.4, 0.5, 0.6]
        health = compute_distribution_health(values, target_mean=0.4)
        assert health["health_score"] > 0.6

    def test_unhealthy_bimodal(self):
        """All-hot-or-all-cold should be flagged."""
        values = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]
        health = compute_distribution_health(values, target_mean=0.4)
        assert health["health_score"] < 0.8

    def test_unhealthy_off_target(self):
        values = [0.9, 0.95, 0.85, 0.92]
        health = compute_distribution_health(values, target_mean=0.4)
        assert health["deviation_from_target"] > 0.4

    def test_empty_values(self):
        health = compute_distribution_health([], target_mean=0.4)
        assert health["health_score"] == 0.0

    def test_returns_all_fields(self):
        health = compute_distribution_health([0.5], target_mean=0.4)
        expected_keys = {
            "mean",
            "std",
            "skew",
            "kurtosis_excess",
            "deviation_from_target",
            "bimodality_coefficient",
            "health_score",
        }
        assert set(health.keys()) == expected_keys
