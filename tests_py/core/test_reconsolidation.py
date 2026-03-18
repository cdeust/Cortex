"""Tests for mcp_server.core.reconsolidation — memory lability after retrieval."""

from datetime import datetime, timezone, timedelta

from mcp_server.core.reconsolidation import (
    compute_mismatch,
    decide_action,
    merge_content,
    compute_plasticity_decay,
    update_stability,
)


class TestComputeMismatch:
    def test_identical_context_low_mismatch(self):
        result = compute_mismatch(
            embedding_similarity=1.0,
            memory_directory="/src",
            current_directory="/src",
            memory_last_accessed=datetime.now(timezone.utc).isoformat(),
            memory_tags={"python", "core"},
            context_tokens={"python", "core"},
        )
        assert result < 0.1

    def test_completely_different_high_mismatch(self):
        old = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        result = compute_mismatch(
            embedding_similarity=0.0,
            memory_directory="/old-project",
            current_directory="/new-project",
            memory_last_accessed=old,
            memory_tags={"java"},
            context_tokens={"python"},
        )
        assert result > 0.7

    def test_no_embedding_defaults_half(self):
        result = compute_mismatch(
            embedding_similarity=None,
            memory_directory="/src",
            current_directory="/src",
            memory_last_accessed=None,
            memory_tags=set(),
            context_tokens=set(),
        )
        # 0.5*0.5 + 0.2*0.0 + 0.15*0.5 + 0.15*0.0 = 0.325
        assert 0.3 <= result <= 0.35

    def test_sibling_directory_partial_distance(self):
        result = compute_mismatch(
            embedding_similarity=1.0,
            memory_directory="/project/src",
            current_directory="/project/tests",
            memory_last_accessed=datetime.now(timezone.utc).isoformat(),
            memory_tags=set(),
            context_tokens=set(),
        )
        # dir distance = 0.5 (sibling), others low
        assert result > 0.0

    def test_bounded_zero_to_one(self):
        result = compute_mismatch(
            embedding_similarity=0.0,
            memory_directory="/a",
            current_directory="/b",
            memory_last_accessed=(
                datetime.now(timezone.utc) - timedelta(days=30)
            ).isoformat(),
            memory_tags={"x"},
            context_tokens={"y"},
        )
        assert 0.0 <= result <= 1.0


class TestDecideAction:
    def test_low_mismatch_no_action(self):
        assert decide_action(0.1) == "none"

    def test_medium_mismatch_update(self):
        assert decide_action(0.5) == "update"

    def test_high_mismatch_archive(self):
        assert decide_action(0.85) == "archive"

    def test_protected_always_none(self):
        assert decide_action(0.9, is_protected=True) == "none"

    def test_stable_memory_needs_more_mismatch(self):
        # Without stability: 0.35 > 0.3 => update
        assert decide_action(0.35, stability=0.0) == "update"
        # With high stability: effective_low = 0.3 + 0.2*1.0 = 0.5 => none
        assert decide_action(0.35, stability=1.0) == "none"

    def test_high_plasticity_lowers_thresholds(self):
        # Normally 0.25 < 0.3 => none
        assert decide_action(0.25, plasticity=0.3) == "none"
        # With high plasticity: effective_low = 0.3 - 0.1 = 0.2 => 0.25 > 0.2 => update
        assert decide_action(0.25, plasticity=0.8) == "update"


class TestMergeContent:
    def test_short_merge(self):
        result = merge_content("old info", "new info")
        assert "old info" in result
        assert "new info" in result
        assert "Updated context" in result

    def test_long_merge_truncates(self):
        old = "A" * 2000
        new = "B" * 100
        result = merge_content(old, new, max_length=1500)
        assert len(result) < 2500
        assert "B" * 100 in result

    def test_respects_max_length_structure(self):
        old = "prefix " * 200  # >500 chars
        new = "update"
        result = merge_content(old, new, max_length=800)
        assert "..." in result  # truncation indicator


class TestPlasticityDecay:
    def test_spike_on_access(self):
        result = compute_plasticity_decay(0.5, 0.0, spike=0.3)
        assert abs(result - 0.8) < 1e-9

    def test_decay_then_spike(self):
        result = compute_plasticity_decay(1.0, 6.0, half_life_hours=6.0, spike=0.3)
        # 1.0 * 2^(-1) + 0.3 = 0.8
        assert abs(result - 0.8) < 1e-9

    def test_caps_at_one(self):
        result = compute_plasticity_decay(0.9, 0.0, spike=0.3)
        assert result == 1.0


class TestUpdateStability:
    def test_useful_increases_stability(self):
        assert update_stability(0.5, was_useful=True, access_count=1) == 0.6

    def test_not_useful_frequent_decreases(self):
        result = update_stability(0.5, was_useful=False, access_count=10, increment=0.1)
        assert result == 0.45

    def test_not_useful_low_access_no_change(self):
        assert update_stability(0.5, was_useful=False, access_count=3) == 0.5

    def test_caps_at_one(self):
        assert update_stability(0.95, was_useful=True, access_count=1) == 1.0

    def test_floor_at_zero(self):
        assert update_stability(0.01, was_useful=False, access_count=10) == 0.0
