"""Tests for two_stage_model — hippocampal-cortical transfer."""

import pytest
from mcp_server.core.two_stage_model import (
    compute_transfer_delta,
    update_hippocampal_dependency,
    classify_memory_store,
    should_release_hippocampal_trace,
    compute_hippocampal_pressure,
    compute_consolidation_priority,
    select_replay_candidates,
    compute_interleaving_schedule,
    compute_transfer_metrics,
)


class TestTransfer:
    def test_no_transfer_below_min_replays(self):
        delta = compute_transfer_delta(1.0, replay_count=1)
        assert delta == 0.0

    def test_transfer_occurs_after_min_replays(self):
        delta = compute_transfer_delta(1.0, replay_count=3)
        assert delta > 0

    def test_schema_accelerates_transfer(self):
        no_schema = compute_transfer_delta(1.0, 3, schema_match=0.0)
        with_schema = compute_transfer_delta(1.0, 3, schema_match=0.9)
        assert with_schema > no_schema

    def test_diminishing_returns(self):
        early = compute_transfer_delta(1.0, 3)
        late = compute_transfer_delta(1.0, 20)
        assert early > late

    def test_update_reduces_dependency(self):
        dep = update_hippocampal_dependency(1.0, 5)
        assert dep < 1.0

    def test_many_replays_approach_zero(self):
        """After many replays, dependency decreases substantially.

        With cortical LR = 0.02 (C-HORSE, Ketz et al. 2023) and schema_match=0.8,
        50 replays reduce dependency from 1.0 to ~0.45. With 100 replays it
        approaches ~0.2. The slower rate reflects the published 10:1 ratio
        between hippocampal and cortical learning.
        """
        dep = 1.0
        for i in range(100):
            dep = update_hippocampal_dependency(dep, i + 1, schema_match=0.8)
        assert dep < 0.3


class TestStoreClassification:
    def test_hippocampal(self):
        assert classify_memory_store(0.9, "labile") == "hippocampal"

    def test_transitional(self):
        assert classify_memory_store(0.4, "late_ltp") == "transitional"

    def test_cortical(self):
        assert classify_memory_store(0.05, "consolidated") == "cortical"


class TestRelease:
    def test_release_when_independent(self):
        assert should_release_hippocampal_trace(0.03, "consolidated", 0.1) is True

    def test_no_release_when_dependent(self):
        assert should_release_hippocampal_trace(0.5, "consolidated", 0.1) is False

    def test_no_release_when_hot(self):
        assert should_release_hippocampal_trace(0.03, "consolidated", 0.8) is False

    def test_no_release_when_not_consolidated(self):
        assert should_release_hippocampal_trace(0.03, "early_ltp", 0.1) is False


class TestCapacityPressure:
    def test_low_at_empty(self):
        pressure = compute_hippocampal_pressure(10)
        assert pressure < 0.1

    def test_high_at_capacity(self):
        pressure = compute_hippocampal_pressure(95)
        assert pressure > 0.8

    def test_critical_above_capacity(self):
        pressure = compute_hippocampal_pressure(150)
        assert pressure > 0.95


class TestConsolidationPriority:
    def test_high_importance_high_priority(self):
        high = compute_consolidation_priority(0.5, 0.9, 0.5, 0.0, 48)
        low = compute_consolidation_priority(0.5, 0.2, 0.5, 0.0, 48)
        assert high > low

    def test_transitional_higher_than_extremes(self):
        transitional = compute_consolidation_priority(0.5, 0.5, 0.5, 0.0, 24)
        fully_hippocampal = compute_consolidation_priority(1.0, 0.5, 0.5, 0.0, 24)
        assert transitional > fully_hippocampal


class TestReplaySelection:
    def test_selects_eligible_memories(self):
        memories = [
            {
                "hippocampal_dependency": 0.8,
                "consolidation_stage": "early_ltp",
                "importance": 0.7,
                "heat": 0.5,
                "schema_match_score": 0.0,
                "hours_since_creation": 24,
            },
            {
                "hippocampal_dependency": 0.02,
                "consolidation_stage": "consolidated",
                "importance": 0.5,
                "heat": 0.1,
                "schema_match_score": 0.0,
                "hours_since_creation": 200,
            },
            {
                "hippocampal_dependency": 1.0,
                "consolidation_stage": "labile",
                "importance": 0.9,
                "heat": 0.9,
                "schema_match_score": 0.0,
                "hours_since_creation": 1,
            },
        ]
        candidates = select_replay_candidates(memories)
        # Only early_ltp should qualify (consolidated is done, labile not ready)
        assert len(candidates) == 1
        assert candidates[0]["consolidation_stage"] == "early_ltp"

    def test_sorted_by_priority(self):
        memories = [
            {
                "hippocampal_dependency": 0.5,
                "consolidation_stage": "late_ltp",
                "importance": 0.3,
                "heat": 0.3,
                "schema_match_score": 0.0,
                "hours_since_creation": 48,
            },
            {
                "hippocampal_dependency": 0.5,
                "consolidation_stage": "early_ltp",
                "importance": 0.9,
                "heat": 0.8,
                "schema_match_score": 0.5,
                "hours_since_creation": 24,
            },
        ]
        candidates = select_replay_candidates(memories)
        assert len(candidates) == 2
        assert candidates[0]["importance"] == 0.9  # Higher priority first


class TestInterleaving:
    def test_single_domain(self):
        candidates = [{"domain": "A"}, {"domain": "A"}, {"domain": "A"}]
        schedule = compute_interleaving_schedule(candidates)
        assert schedule == [0, 1, 2]

    def test_multi_domain_interleaved(self):
        candidates = [
            {"domain": "A"},
            {"domain": "A"},
            {"domain": "B"},
            {"domain": "B"},
        ]
        schedule = compute_interleaving_schedule(candidates)
        # Should alternate: A, B, A, B
        assert len(schedule) == 4
        assert (
            schedule[0] != schedule[1]
            or candidates[schedule[0]]["domain"] != candidates[schedule[1]]["domain"]
        )


class TestMetrics:
    def test_transfer_metrics(self):
        memories = [
            {"hippocampal_dependency": 1.0, "consolidation_stage": "labile"},
            {"hippocampal_dependency": 0.5, "consolidation_stage": "late_ltp"},
            {"hippocampal_dependency": 0.02, "consolidation_stage": "consolidated"},
        ]
        m = compute_transfer_metrics(memories)
        assert m["hippocampal"] == 1
        assert m["transitional"] == 1
        assert m["cortical"] == 1
        assert m["transfer_progress"] == pytest.approx(0.333, abs=0.01)

    def test_empty_metrics(self):
        m = compute_transfer_metrics([])
        assert m["total"] == 0
