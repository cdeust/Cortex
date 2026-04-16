"""Write-gate auto-calibration — AF-5 antifragile feedback loop.

Per Taleb's antifragile audit: the write-gate threshold must respond to
observed traffic. These tests verify the EMA logic and the adjustment
direction in isolation (no I/O, no DB).

Invariants under test:
  - update_acceptance_ema converges to 1.0 under all-accept streams and
    to 0.0 under all-reject streams (post-condition of the EMA update).
  - compute_threshold_adjustment moves threshold UP when EMA > target
    (too permissive -> tighten) and DOWN when EMA < target (too tight
    -> loosen).
  - observe_gate_decision respects the min_samples guard (no adjustment
    under cold-start noise).
  - threshold is clamped to [MIN_THRESHOLD, MAX_THRESHOLD].
  - The EMA converges to the target (0.5) under balanced synthetic
    traffic — the control loop is not biased.

Source: Jaynes (2003), Taleb (2012). Target acceptance 0.5 is the
maximum-entropy operating point for a binary gate.
"""

from __future__ import annotations

import pytest

from mcp_server.core import write_gate_calibration as wgc


@pytest.fixture(autouse=True)
def _reset_calibration_registry():
    """Each test starts with an empty calibration registry."""
    wgc.reset_all_states()
    yield
    wgc.reset_all_states()


class TestEmaUpdate:
    """update_acceptance_ema is a pure function — no state, no side effects."""

    def test_all_accepts_converge_to_one(self):
        ema = 0.5
        for _ in range(500):
            ema = wgc.update_acceptance_ema(ema, accepted=True)
        # With decay=0.95 and 500 samples, ema should be essentially 1.0.
        assert ema > 0.999

    def test_all_rejects_converge_to_zero(self):
        ema = 0.5
        for _ in range(500):
            ema = wgc.update_acceptance_ema(ema, accepted=False)
        assert ema < 0.001

    def test_balanced_stream_converges_to_half(self):
        """Perfectly alternating accept/reject converges to ~0.5."""
        ema = 0.5
        for i in range(1000):
            ema = wgc.update_acceptance_ema(ema, accepted=(i % 2 == 0))
        assert 0.45 < ema < 0.55

    def test_output_always_in_unit_interval(self):
        """EMA must stay in [0, 1] for any decay and input."""
        ema = 0.5
        for i in range(100):
            ema = wgc.update_acceptance_ema(ema, accepted=(i % 3 == 0))
            assert 0.0 <= ema <= 1.0


class TestThresholdAdjustment:
    """compute_threshold_adjustment is pure — one decision per call."""

    def test_no_change_inside_tolerance_band(self):
        """EMA close to target -> threshold unchanged."""
        # Target 0.5, tolerance 0.15 -> band [0.35, 0.65].
        new_t = wgc.compute_threshold_adjustment(0.4, acceptance_ema=0.5)
        assert new_t == 0.4

        new_t = wgc.compute_threshold_adjustment(0.4, acceptance_ema=0.62)
        assert new_t == 0.4

        new_t = wgc.compute_threshold_adjustment(0.4, acceptance_ema=0.38)
        assert new_t == 0.4

    def test_high_acceptance_tightens_gate(self):
        """EMA > target + tolerance -> raise threshold."""
        # EMA 0.9 > 0.5 + 0.15 = 0.65 -> threshold goes up by step (0.02).
        new_t = wgc.compute_threshold_adjustment(0.4, acceptance_ema=0.9)
        assert new_t == pytest.approx(0.42, abs=1e-9)

    def test_low_acceptance_loosens_gate(self):
        """EMA < target - tolerance -> lower threshold."""
        # EMA 0.1 < 0.5 - 0.15 = 0.35 -> threshold goes down by step.
        new_t = wgc.compute_threshold_adjustment(0.4, acceptance_ema=0.1)
        assert new_t == pytest.approx(0.38, abs=1e-9)

    def test_threshold_clamped_at_max(self):
        """Threshold never exceeds MAX_THRESHOLD even under sustained pressure."""
        t = wgc.MAX_THRESHOLD
        # Already at ceiling: another 'tighten' signal must not push over.
        new_t = wgc.compute_threshold_adjustment(t, acceptance_ema=1.0)
        assert new_t == wgc.MAX_THRESHOLD

    def test_threshold_clamped_at_min(self):
        """Threshold never falls below MIN_THRESHOLD."""
        t = wgc.MIN_THRESHOLD
        new_t = wgc.compute_threshold_adjustment(t, acceptance_ema=0.0)
        assert new_t == wgc.MIN_THRESHOLD


class TestObserveGateDecision:
    """State lifecycle — combines EMA update + guarded threshold adjustment."""

    def test_no_adjustment_before_min_samples(self):
        """Threshold is frozen for the first MIN_SAMPLES_BEFORE_ADJUST calls."""
        state = wgc.CalibrationState(domain="t", threshold=0.4)
        for _ in range(wgc.MIN_SAMPLES_BEFORE_ADJUST - 1):
            state = wgc.observe_gate_decision(state, accepted=True)
        # Even though EMA is now very high, threshold stayed at 0.4.
        assert state.threshold == 0.4
        assert state.total_observations == wgc.MIN_SAMPLES_BEFORE_ADJUST - 1

    def test_adjustment_fires_after_min_samples(self):
        """Once past MIN_SAMPLES, sustained high-accept traffic raises threshold."""
        state = wgc.CalibrationState(domain="t", threshold=0.4)
        # All-accept for enough samples to pass min_samples and overcome
        # the tolerance band (EMA starts at 0.5, needs to rise above 0.65).
        # With decay 0.95, EMA after k accepts from 0.5 is:
        #   EMA_k = 1 - 0.5 * 0.95^k
        # 0.65 exceeded when 0.95^k < 0.70 -> k >= 8.
        # But min_samples is 20, so we need at least 20 observations.
        for _ in range(50):
            state = wgc.observe_gate_decision(state, accepted=True)
        # Threshold must have moved up from the 0.4 seed.
        assert state.threshold > 0.4
        assert state.threshold <= wgc.MAX_THRESHOLD

    def test_low_novelty_stream_drifts_threshold_down(self):
        """Repeated low-novelty (rejection) traffic lowers the threshold."""
        # Start with a threshold above the seed to give room to fall.
        state = wgc.CalibrationState(domain="t", threshold=0.7)
        for _ in range(80):
            state = wgc.observe_gate_decision(state, accepted=False)
        # Threshold fell from 0.7 toward MIN_THRESHOLD.
        assert state.threshold < 0.7
        assert state.threshold >= wgc.MIN_THRESHOLD

    def test_high_novelty_stream_drifts_threshold_up(self):
        """Repeated high-novelty (accept) traffic raises the threshold."""
        state = wgc.CalibrationState(domain="t", threshold=0.3)
        for _ in range(80):
            state = wgc.observe_gate_decision(state, accepted=True)
        assert state.threshold > 0.3
        assert state.threshold <= wgc.MAX_THRESHOLD

    def test_balanced_stream_ema_converges_to_target(self):
        """Synthetic 50/50 traffic drives EMA to ~0.5 and keeps threshold still."""
        state = wgc.CalibrationState(domain="t", threshold=0.4)
        for i in range(500):
            state = wgc.observe_gate_decision(state, accepted=(i % 2 == 0))
        # EMA converged near target; threshold stayed near its seed (moved
        # at most one step away before settling in the tolerance band).
        assert 0.45 < state.acceptance_ema < 0.55
        assert abs(state.threshold - 0.4) <= wgc.ADJUSTMENT_STEP * 2


class TestRegistry:
    """Per-domain state isolation and record() convenience."""

    def test_different_domains_have_independent_state(self):
        wgc.record("alpha", accepted=True)
        wgc.record("beta", accepted=False)
        alpha = wgc.get_state("alpha")
        beta = wgc.get_state("beta")
        assert alpha.total_observations == 1
        assert beta.total_observations == 1
        # EMA moved in different directions for the two domains.
        assert alpha.acceptance_ema > beta.acceptance_ema

    def test_effective_threshold_falls_back_to_default(self):
        """No state -> caller's default is returned unchanged."""
        t = wgc.effective_threshold("unseen-domain", default_threshold=0.42)
        assert t == 0.42

    def test_effective_threshold_reflects_calibration_after_drift(self):
        """After enough accept-heavy calls, effective_threshold > default."""
        for _ in range(100):
            wgc.record("busy", accepted=True, default_threshold=0.4)
        t = wgc.effective_threshold("busy", default_threshold=0.4)
        assert t > 0.4
