"""Tests for recall handler enhancements: recency boost + strategic ordering."""

from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.core.temporal import compute_recency_boost as _compute_recency_boost
from mcp_server.handlers.recall import _apply_strategic_ordering


# ── Recency Boost ────────────────────────────────────────────────────────


class TestRecencyBoost:
    def test_brand_new_memory_gets_max_boost(self):
        now = datetime.now(timezone.utc).isoformat()
        boost = _compute_recency_boost(now)
        assert boost == pytest.approx(0.15, abs=0.01)

    def test_old_memory_gets_no_boost(self):
        old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        boost = _compute_recency_boost(old)
        assert boost == 0.0

    def test_30_day_old_memory_gets_half_boost(self):
        dt = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        boost = _compute_recency_boost(dt, halflife_days=30.0)
        expected = 0.15 * 0.5  # Half-life = half boost
        assert boost == pytest.approx(expected, abs=0.01)

    def test_decay_is_monotonic(self):
        boosts = []
        for days in [0, 7, 14, 30, 60, 89]:
            dt = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            boosts.append(_compute_recency_boost(dt))
        for i in range(len(boosts) - 1):
            assert boosts[i] >= boosts[i + 1]

    def test_cutoff_enforced(self):
        dt = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
        assert _compute_recency_boost(dt, cutoff_days=90.0) == 0.0

    def test_invalid_timestamp_returns_zero(self):
        assert _compute_recency_boost("not-a-date") == 0.0
        assert _compute_recency_boost("") == 0.0
        assert _compute_recency_boost(None) == 0.0

    def test_datetime_object_accepted(self):
        dt = datetime.now(timezone.utc) - timedelta(days=1)
        boost = _compute_recency_boost(dt)
        assert boost > 0.0

    def test_naive_datetime_handled(self):
        dt = datetime.utcnow() - timedelta(days=1)
        boost = _compute_recency_boost(dt)
        assert boost > 0.0

    def test_custom_boost_max(self):
        now = datetime.now(timezone.utc).isoformat()
        boost = _compute_recency_boost(now, boost_max=0.5)
        assert boost == pytest.approx(0.5, abs=0.01)


# ── Strategic Ordering ───────────────────────────────────────────────────


class TestStrategicOrdering:
    def _make_results(self, n: int) -> list[dict]:
        return [{"memory_id": i, "score": 1.0 - i * 0.05} for i in range(n)]

    def test_few_results_unchanged(self):
        results = self._make_results(3)
        ordered = _apply_strategic_ordering(results)
        assert ordered == results

    def test_ten_results_reordered(self):
        results = self._make_results(10)
        ordered = _apply_strategic_ordering(results)
        assert len(ordered) == 10

        # Top 30% (3 items) should be at start
        assert ordered[0]["memory_id"] == 0
        assert ordered[1]["memory_id"] == 1
        assert ordered[2]["memory_id"] == 2

    def test_preserves_all_items(self):
        results = self._make_results(15)
        ordered = _apply_strategic_ordering(results)
        original_ids = {r["memory_id"] for r in results}
        ordered_ids = {r["memory_id"] for r in ordered}
        assert original_ids == ordered_ids

    def test_top_results_stay_at_top(self):
        results = self._make_results(20)
        ordered = _apply_strategic_ordering(results)
        # First 6 items (30% of 20) should be the top-scoring
        top_ids = {r["memory_id"] for r in ordered[:6]}
        expected_top = {0, 1, 2, 3, 4, 5}
        assert top_ids == expected_top

    def test_custom_fractions(self):
        results = self._make_results(10)
        ordered = _apply_strategic_ordering(
            results, top_fraction=0.5, bottom_fraction=0.3
        )
        assert len(ordered) == 10
        # Top 50% = 5 items at start
        for i in range(5):
            assert ordered[i]["memory_id"] == i

    def test_single_result(self):
        results = self._make_results(1)
        assert _apply_strategic_ordering(results) == results

    def test_empty_results(self):
        assert _apply_strategic_ordering([]) == []
