"""Tests for Fix 1 of issue #14 P1 — age-decayed initial heat for backfills.

Covers:
- age_decayed_heat unit behavior at the reference ages.
- compute_age_days unit behavior with ISO / trailing-Z / bad inputs.
- Integration: simulating a distribution of backfilled memories produces
  a spread heat distribution (NOT a unimodal peak at 1.0).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from mcp_server.handlers.backfill_helpers import (
    age_decayed_heat,
    compute_age_days,
)


class TestAgeDecayedHeat:
    def test_fresh_returns_one(self):
        assert age_decayed_heat(0.0) == pytest.approx(1.0)

    def test_one_week(self):
        # exp(-7 * ln(2) / 30) ≈ 0.8513; floor + 0.7 * 0.8513 ≈ 0.8959
        assert age_decayed_heat(7.0) == pytest.approx(0.8959, abs=0.005)

    def test_one_month_halves_gap_to_floor(self):
        # half-life = 30 days; gap to floor halves; h(30) = 0.3 + 0.7 * 0.5 = 0.65
        assert age_decayed_heat(30.0) == pytest.approx(0.65, abs=0.005)

    def test_three_months(self):
        # h(90) = 0.3 + 0.7 * exp(-90 * ln2 / 30) = 0.3 + 0.7 * 0.125 ≈ 0.3875
        assert age_decayed_heat(90.0) == pytest.approx(0.3875, abs=0.005)

    def test_six_months_near_floor(self):
        assert age_decayed_heat(180.0) == pytest.approx(0.3109, abs=0.005)

    def test_one_year_near_floor(self):
        assert age_decayed_heat(365.0) < 0.31

    def test_floor_not_crossed_even_at_huge_ages(self):
        assert age_decayed_heat(10_000.0) >= 0.3

    def test_monotone_non_increasing(self):
        ages = [0, 1, 7, 14, 30, 60, 90, 180, 365]
        heats = [age_decayed_heat(a) for a in ages]
        for i in range(len(heats) - 1):
            assert heats[i] >= heats[i + 1]

    def test_negative_age_clamps_to_fresh(self):
        assert age_decayed_heat(-5.0) == pytest.approx(1.0)

    def test_custom_half_life(self):
        # shorter half-life → faster decay at the same age
        fast = age_decayed_heat(30.0, half_life_days=10.0)
        slow = age_decayed_heat(30.0, half_life_days=30.0)
        assert fast < slow

    def test_custom_floor(self):
        # higher floor → higher asymptote at large ages
        high = age_decayed_heat(10_000.0, floor=0.5)
        assert high == pytest.approx(0.5)


class TestComputeAgeDays:
    def test_none_returns_zero(self):
        assert compute_age_days(None) == 0.0

    def test_empty_returns_zero(self):
        assert compute_age_days("") == 0.0

    def test_unparseable_returns_zero(self):
        assert compute_age_days("not-a-timestamp") == 0.0

    def test_iso_with_z(self):
        now = datetime(2026, 4, 16, tzinfo=timezone.utc)
        ts = "2026-04-09T00:00:00Z"
        assert compute_age_days(ts, now=now) == pytest.approx(7.0, abs=0.01)

    def test_iso_with_offset(self):
        now = datetime(2026, 4, 16, tzinfo=timezone.utc)
        ts = "2026-04-16T00:00:00+00:00"
        assert compute_age_days(ts, now=now) == pytest.approx(0.0, abs=0.01)

    def test_future_timestamp_returns_zero(self):
        # Clock skew: future → age 0 (treat as fresh, don't crash).
        now = datetime(2026, 4, 16, tzinfo=timezone.utc)
        ts = "2026-05-16T00:00:00Z"
        assert compute_age_days(ts, now=now) == 0.0

    def test_naive_datetime_assumed_utc(self):
        now = datetime(2026, 4, 16, tzinfo=timezone.utc)
        ts = "2026-04-09T00:00:00"  # no tz
        assert compute_age_days(ts, now=now) == pytest.approx(7.0, abs=0.01)


class TestBackfillDistribution:
    """A mix of recent + old backfills produces a SPREAD heat distribution."""

    def test_distribution_spread_across_180_days(self):
        # 100 memories, ages uniformly spread in [0, 180]
        ages = [i * 180.0 / 99 for i in range(100)]
        heats = [age_decayed_heat(a) for a in ages]

        mean = sum(heats) / len(heats)
        var = sum((h - mean) ** 2 for h in heats) / len(heats)
        std = math.sqrt(var)

        # NOT a unimodal peak at 1.0. Measured on the actual curve: range
        # ~0.69, std ~0.18, mean ~0.47. Asserting comfortably below measured.
        assert max(heats) - min(heats) >= 0.5
        assert std >= 0.15
        assert mean < 0.7  # not dominated by the peak

    def test_all_fresh_collapses_to_one(self):
        # Sanity: if every memory is fresh, the curve still gives 1.0 each.
        heats = [age_decayed_heat(0.0) for _ in range(50)]
        assert all(h == pytest.approx(1.0) for h in heats)
