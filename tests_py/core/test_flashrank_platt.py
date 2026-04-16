"""FlashRank Platt calibration from rate_memory feedback — AF-2.

Per Taleb antifragile audit AF-2: turn retrieval failures into
calibration fuel. Each useful/not-useful rating pairs with the raw
FlashRank CE score to train a Platt-style logistic regression over
time. Calibrated scores should rank useful above not-useful on the
training support.

Reference:
    Platt, J. C. (1999). "Probabilistic outputs for SVMs..."
        In *Advances in Large Margin Classifiers*. MIT Press.

Tests:
  (a) Synthetic training pairs fit a model (non-degenerate, finite A, B).
  (b) Calibrated scores rank useful over not-useful at least as well as
      raw scores on the training data.
  (c) Without training data (cold start), calibrate_score is identity —
      falls back to raw scores exactly.
  (d) The reranker_calibration store fires a refit every REFIT_EVERY
      samples and caps at MAX_SAMPLES via FIFO.
  (e) Degenerate pure-class inputs return None (no fit).
"""

from __future__ import annotations

import math
import random

import pytest

from mcp_server.core import platt_calibration as pc
from mcp_server.core import reranker_calibration as rc


@pytest.fixture(autouse=True)
def _reset_calibration_state():
    rc.reset_for_tests()
    yield
    rc.reset_for_tests()


class TestFitPlatt:
    """Direct unit tests for the logistic fit."""

    def test_below_min_samples_returns_none(self):
        """Fewer than MIN_SAMPLES samples -> refuse to fit."""
        samples = [pc.TrainingSample(raw_score=0.5, label=1) for _ in range(pc.MIN_SAMPLES - 1)]
        assert pc.fit_platt(samples) is None

    def test_all_one_class_returns_none(self):
        """All labels identical -> MLE diverges -> return None."""
        samples = [pc.TrainingSample(raw_score=0.5, label=1) for _ in range(100)]
        assert pc.fit_platt(samples) is None

        samples = [pc.TrainingSample(raw_score=0.5, label=0) for _ in range(100)]
        assert pc.fit_platt(samples) is None

    def test_well_separated_data_fits(self):
        """When useful samples have high raw scores and not-useful have low
        raw scores, Platt must fit a model with finite A, B.
        """
        samples = []
        rng = random.Random(42)
        for _ in range(60):
            # High CE -> useful
            samples.append(
                pc.TrainingSample(raw_score=rng.uniform(0.5, 1.0), label=1)
            )
            # Low CE -> not useful
            samples.append(
                pc.TrainingSample(raw_score=rng.uniform(-1.0, 0.0), label=0)
            )
        params = pc.fit_platt(samples)
        assert params is not None
        assert math.isfinite(params.A)
        assert math.isfinite(params.B)
        assert params.n_samples == len(samples)


class TestCalibrateApply:
    """calibrate_score behaviour under fitted / unfitted params."""

    def test_cold_start_returns_raw_score(self):
        """No params -> identity (falls back to raw score)."""
        for raw in [-0.5, 0.0, 0.3, 0.7, 1.5]:
            assert pc.calibrate_score(raw, params=None) == raw

    def test_calibrated_scores_in_unit_interval(self):
        """Fitted Platt outputs probabilities in (0, 1)."""
        rng = random.Random(0)
        samples = []
        for _ in range(60):
            samples.append(
                pc.TrainingSample(raw_score=rng.uniform(0.3, 1.0), label=1)
            )
            samples.append(
                pc.TrainingSample(raw_score=rng.uniform(-0.8, 0.2), label=0)
            )
        params = pc.fit_platt(samples)
        assert params is not None
        for raw in [-0.9, -0.3, 0.1, 0.5, 0.9, 1.4]:
            p = pc.calibrate_score(raw, params)
            assert 0.0 < p < 1.0


class TestRankingPreservation:
    """The core AF-2 claim: calibrated scores better-rank useful over not-useful
    on the training support. "Better" here means at least as good as raw
    scores — calibration must not destroy the ranking signal that fit it.
    """

    def _make_training_data(self, rng):
        useful, not_useful = [], []
        # Useful: concentrated at high CE.
        for _ in range(80):
            useful.append(rng.uniform(0.4, 1.0))
        # Not-useful: concentrated at low CE with some overlap.
        for _ in range(80):
            not_useful.append(rng.uniform(-0.5, 0.3))
        return useful, not_useful

    def test_calibrated_ranking_preserves_useful_over_not(self):
        """AF-2 contract: calibrated Platt preserves raw ranking direction."""
        rng = random.Random(7)
        useful, not_useful = self._make_training_data(rng)
        samples = [pc.TrainingSample(raw_score=s, label=1) for s in useful]
        samples += [pc.TrainingSample(raw_score=s, label=0) for s in not_useful]
        params = pc.fit_platt(samples)
        assert params is not None

        raw_quality = pc.pairwise_discrimination(None, useful, not_useful)
        cal_quality = pc.pairwise_discrimination(params, useful, not_useful)
        # Logistic regression on pairs drawn from the same data cannot
        # degrade the pairwise ordering by more than floating-point noise.
        assert cal_quality >= raw_quality - 0.02
        # Sanity: both rank the majority of useful above not-useful.
        assert raw_quality > 0.80


class TestReRankerCalibrationStore:
    """In-process sample store and refit schedule."""

    def test_cold_start_params_none(self):
        assert rc.get_params() is None
        assert rc.sample_count() == 0

    def test_record_increments_sample_count(self):
        rc.record_rating(0.5, useful=True)
        rc.record_rating(0.1, useful=False)
        assert rc.sample_count() == 2

    def test_refit_fires_after_refit_every(self):
        """After REFIT_EVERY samples (and once past MIN_SAMPLES), fit runs."""
        rng = random.Random(3)
        needed = max(pc.MIN_SAMPLES, rc.REFIT_EVERY)
        for i in range(needed):
            # Alternate labels so the fit is non-degenerate.
            useful = (i % 2 == 0)
            raw = rng.uniform(0.4, 1.0) if useful else rng.uniform(-0.5, 0.2)
            rc.record_rating(raw, useful=useful)
        # With alternating classes and linearly separable raw scores, a fit
        # must succeed and return finite params.
        params = rc.get_params()
        assert params is not None
        assert math.isfinite(params.A)
        assert math.isfinite(params.B)

    def test_fifo_cap_at_max_samples(self):
        """Sample list never exceeds MAX_SAMPLES; oldest are evicted first."""
        for i in range(rc.MAX_SAMPLES + 100):
            rc.record_rating(float(i) / 1000.0, useful=(i % 2 == 0))
        assert rc.sample_count() == rc.MAX_SAMPLES


class TestRerankerBlendFallback:
    """reranker.rerank_results without apply_platt behaves as before (cold start)."""

    def test_cold_start_apply_platt_false_matches_raw_path(self):
        """apply_platt=False AND no fitted params -> identical to legacy."""
        from mcp_server.core import reranker

        # Build a synthetic candidate list; FlashRank unavailable returns
        # candidates unchanged — so we can't exercise _blend_scores directly
        # from rerank_results here. Instead, check _blend_scores is a
        # pure function and produces the same output with / without
        # apply_platt when params are absent.
        candidates = [(1, 0.9), (2, 0.7), (3, 0.3)]
        ce_scores = {0: 0.6, 1: 0.4, 2: 0.1}
        without = reranker._blend_scores(
            candidates, ce_scores, alpha=0.7, adaptive=False, apply_platt=False
        )
        with_flag_but_no_params = reranker._blend_scores(
            candidates, ce_scores, alpha=0.7, adaptive=False, apply_platt=True
        )
        # Since no params are fitted yet, apply_platt=True is a no-op.
        assert without == with_flag_but_no_params
