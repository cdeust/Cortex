"""Tests for mcp_server.core.streaming.adaptive_controller — AIMD batch sizing."""

import pytest

from mcp_server.core.streaming.adaptive_controller import (
    AdaptiveBatchController,
    adaptive_batch_controller_batch_size,
    adaptive_batch_controller_observe,
)


class TestConstruction:
    def test_starts_at_b_min(self):
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5)
        assert adaptive_batch_controller_batch_size(c) == 100

    def test_ai_step_defaults_to_b_min(self):
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5)
        assert c.ai_step == 100

    def test_explicit_ai_step_honored(self):
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5, ai_step=50)
        assert c.ai_step == 50

    @pytest.mark.parametrize("b_min,b_max", [(0, 10), (-1, 10), (100, 50)])
    def test_rejects_bad_bounds(self, b_min, b_max):
        with pytest.raises(ValueError):
            AdaptiveBatchController(b_min=b_min, b_max=b_max, w_target_s=0.5)

    def test_rejects_nonpositive_target(self):
        with pytest.raises(ValueError):
            AdaptiveBatchController(b_min=10, b_max=100, w_target_s=0.0)


class TestAdditiveIncrease:
    def test_within_target_grows_by_ai_step(self):
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5, ai_step=200)
        assert adaptive_batch_controller_observe(c, 0.1) == 300
        assert adaptive_batch_controller_observe(c, 0.1) == 500

    def test_increase_clamps_at_b_max(self):
        c = AdaptiveBatchController(b_min=100, b_max=250, w_target_s=0.5, ai_step=200)
        assert (
            adaptive_batch_controller_observe(c, 0.1) == 250
        )  # 100 + 200 = 300 -> clamped
        assert adaptive_batch_controller_observe(c, 0.1) == 250  # stays clamped

    def test_latency_equal_to_target_is_within(self):
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5, ai_step=100)
        assert (
            adaptive_batch_controller_observe(c, 0.5) == 200
        )  # <= target counts as within


class TestMultiplicativeDecrease:
    def test_over_target_halves(self):
        c = AdaptiveBatchController(b_min=10, b_max=10000, w_target_s=0.5, ai_step=100)
        adaptive_batch_controller_observe(c, 0.1)  # 10 -> 110
        adaptive_batch_controller_observe(c, 0.1)  # 110 -> 210
        assert (
            adaptive_batch_controller_observe(c, 1.0) == 105
        )  # over target -> floor(210 * 0.5)

    def test_decrease_clamps_at_b_min(self):
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5)
        assert (
            adaptive_batch_controller_observe(c, 5.0) == 100
        )  # floor(100*0.5)=50 -> clamped to b_min


class TestConvergence:
    def test_oscillates_around_a_stable_band(self):
        """AIMD converges to a band: grows until it overshoots, halves, repeats.

        Model the DB as: latency exceeds target once B passes a capacity knee.
        After warmup the controller must stay bounded in [b_min, b_max] and
        never run away — the whole point of multiplicative decrease.
        """
        knee = 2000
        c = AdaptiveBatchController(b_min=100, b_max=10000, w_target_s=0.5, ai_step=100)
        seen = []
        for _ in range(500):
            latency = 0.1 if adaptive_batch_controller_batch_size(c) <= knee else 1.0
            seen.append(adaptive_batch_controller_observe(c, latency))
        # Never escapes the hard bounds (invariant precond 4).
        assert all(100 <= b <= 10000 for b in seen)
        # Settles near the knee, never near b_max runaway.
        tail = seen[-50:]
        assert max(tail) <= knee + 100
        assert min(tail) >= knee // 2 - 100
