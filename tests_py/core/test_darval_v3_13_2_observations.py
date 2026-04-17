"""Tests for darval's v3.13.2 consolidate-report observations (P2/P3).

Source: GitHub issue #14 comment 2026-04-17T13:40:47Z. darval's field
report after upgrading to v3.13.2 flagged three observability gaps:

  O1 (P2) — bimodality vs cohort_correction effectiveness — diagnosis only
  O2 (P2) — schema_acceleration bootstrap guard (this module)
  O3 (P3) — forgetting_curve fit quality flag (this module)
"""

from __future__ import annotations

import pytest

from mcp_server.core.emergence_metrics import (
    _fit_quality_for,
    compute_forgetting_curve,
)
from mcp_server.core.emergence_tracker import compute_schema_acceleration_metric


# ── O3: forgetting_curve fit_quality ─────────────────────────────────────


class TestFitQualityBuckets:
    @pytest.mark.parametrize(
        "r2,expected",
        [
            (0.0, "poor"),
            (0.001, "poor"),  # darval's actual value
            (0.05, "poor"),
            (0.10, "weak"),  # threshold inclusive
            (0.30, "weak"),
            (0.50, "good"),  # threshold inclusive
            (0.80, "good"),
            (1.0, "good"),
        ],
    )
    def test_bucket_boundaries(self, r2, expected):
        assert _fit_quality_for(r2) == expected


class TestForgettingCurveEmitsFitQuality:
    def test_insufficient_data_returns_insufficient_flag(self):
        out = compute_forgetting_curve([])
        assert out["fit_quality"] == "insufficient_data"

    def test_too_few_bins(self):
        # Only 3 memories — below bin minimum of 3.
        out = compute_forgetting_curve([(0.1, 0.9), (0.2, 0.8), (0.3, 0.7)])
        assert "fit_quality" in out

    def test_good_fit_labeled(self):
        # Synthetic data following clean exponential decay.
        # Bin width is 6 hours — span 0..240 hours so we get ~40 bins.
        import math

        data = []
        for i in range(200):
            age = i * 1.2  # 0 → 240 hours
            heat = 0.9 * math.exp(-0.01 * age)
            data.append((age, heat))
        out = compute_forgetting_curve(data)
        assert out["curve_type"] == "exponential"
        assert out["r_squared"] > 0.9
        assert out["fit_quality"] == "good"

    def test_noisy_fit_labeled_poor(self):
        import random

        rng = random.Random(42)
        # Random-uniform heat vs age: no signal → r² ≈ 0.
        # Span many bins to get past the 3-bin minimum.
        data = [(float(i * 2), rng.uniform(0.1, 0.9)) for i in range(100)]
        out = compute_forgetting_curve(data)
        assert out["curve_type"] == "exponential"
        assert out["fit_quality"] in ("poor", "weak")


# ── O2: schema_acceleration bootstrap guard ──────────────────────────────


class TestSchemaAccelerationBootstrap:
    def test_zero_consistent_flags_undefined(self):
        """Darval's exact case: 66439 inconsistent, 0 consistent — bootstrap
        state where no schemas have been promoted yet."""
        out = compute_schema_acceleration_metric([], [{"id": 1}] * 10)
        assert out["consistent_count"] == 0
        assert out["inconsistent_count"] == 10
        assert out["ratio_defined"] is False
        assert out["reason_for_undefined"] == "no_schemas_promoted_yet"
        # Ratio stays 1.0 as a sentinel; consumers check ratio_defined first.
        assert out["acceleration_ratio"] == 1.0

    def test_zero_inconsistent_flags_undefined(self):
        out = compute_schema_acceleration_metric([{"id": 1}], [])
        assert out["ratio_defined"] is False
        assert out["reason_for_undefined"] == "no_baseline_population"

    def test_both_populated_no_consolidated_memories(self):
        """Both buckets have memories but none have reached consolidated
        stage yet — ratio can't be computed from consolidation times."""
        out = compute_schema_acceleration_metric(
            [{"id": 1, "consolidation_stage": "labile", "created_at": None}],
            [{"id": 2, "consolidation_stage": "labile", "created_at": None}],
        )
        assert out["ratio_defined"] is False
        assert out["reason_for_undefined"] == "no_consolidated_memories"

    def test_populated_and_defined(self):
        """Happy path: both buckets have consolidated memories."""
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=100)).isoformat()
        out = compute_schema_acceleration_metric(
            [
                {
                    "id": 1,
                    "consolidation_stage": "consolidated",
                    "created_at": old,
                }
            ],
            [
                {
                    "id": 2,
                    "consolidation_stage": "consolidated",
                    "created_at": old,
                }
            ],
        )
        assert out["ratio_defined"] is True
        assert "reason_for_undefined" not in out
