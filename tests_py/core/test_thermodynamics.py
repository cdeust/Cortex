"""Tests for mcp_server.core.thermodynamics — heat, surprise, decay, importance, valence."""

from datetime import datetime, timezone, timedelta

from mcp_server.core.thermodynamics import (
    compute_surprise,
    apply_surprise_boost,
    compute_importance,
    compute_valence,
    compute_decay,
    compute_session_coherence,
    compute_metamemory_confidence,
    is_error_content,
    is_decision_content,
)


class TestComputeSurprise:
    def test_no_existing_memories_returns_half(self):
        assert compute_surprise("new content", []) == 0.5

    def test_identical_memory_zero_surprise(self):
        assert compute_surprise("same", [1.0]) == 0.0

    def test_novel_content_high_surprise(self):
        result = compute_surprise("totally new", [0.1, 0.2])
        assert result == 0.8  # 1.0 - 0.2

    def test_multiple_similarities_uses_max(self):
        result = compute_surprise("x", [0.3, 0.9, 0.5])
        assert abs(result - 0.1) < 1e-9

    def test_clamps_to_zero(self):
        result = compute_surprise("x", [1.5])  # edge: sim > 1.0
        assert result == 0.0


class TestApplySurpriseBoost:
    def test_zero_surprise_no_boost(self):
        assert apply_surprise_boost(1.0, 0.0) == 1.0

    def test_full_surprise_caps_at_one(self):
        result = apply_surprise_boost(1.0, 1.0, 0.3)
        assert result == 1.0

    def test_partial_surprise(self):
        result = apply_surprise_boost(0.5, 0.5, 0.3)
        assert abs(result - 0.65) < 1e-9


class TestComputeImportance:
    def test_empty_content(self):
        assert compute_importance("") == 0.0

    def test_error_keywords(self):
        result = compute_importance("An error occurred in the system")
        assert result >= 0.2

    def test_decision_keywords(self):
        result = compute_importance("We decided to use PostgreSQL")
        assert result >= 0.3

    def test_architecture_keywords(self):
        result = compute_importance("Refactor the module architecture")
        assert result >= 0.2

    def test_multiple_signals_stack(self):
        result = compute_importance(
            "We decided to refactor the architecture after a failure",
            tags=["important", "critical", "arch"],
        )
        # decision(0.3) + architecture(0.2) + error(0.2) + tags>=3(0.1) = 0.8
        assert result >= 0.7

    def test_long_content_bonus(self):
        content = "word " * 200  # >500 chars
        result = compute_importance(content)
        assert result >= 0.1

    def test_code_blocks(self):
        result = compute_importance("Here is ```code``` to fix it")
        assert result >= 0.1

    def test_file_paths(self):
        result = compute_importance("Check src/core/module.py")
        assert result >= 0.1

    def test_capped_at_one(self):
        # All signals firing
        result = compute_importance(
            "Decided to refactor design after error in src/x.py " + "x" * 500,
            tags=["a", "b", "c"],
        )
        assert result <= 1.0


class TestComputeValence:
    def test_neutral_content(self):
        assert compute_valence("hello world") == 0.0

    def test_negative_valence(self):
        result = compute_valence("error error error failure")
        assert result < 0.0

    def test_positive_valence(self):
        result = compute_valence("fixed resolved working success")
        assert result > 0.0

    def test_mixed_signals(self):
        result = compute_valence("fixed the error")
        # 1 positive, 1 negative => 0.0
        assert result == 0.0

    def test_bounded(self):
        assert compute_valence("error " * 50) >= -1.0
        assert compute_valence("success " * 50) <= 1.0


class TestComputeDecay:
    def test_zero_hours_no_decay(self):
        assert compute_decay(1.0, 0) == 1.0

    def test_negative_hours_no_decay(self):
        assert compute_decay(0.8, -1.0) == 0.8

    def test_basic_decay(self):
        result = compute_decay(1.0, 1.0, importance=0.3, valence=0.0)
        # 0.95^1 = 0.95
        assert abs(result - 0.95) < 0.01

    def test_important_content_slower_decay(self):
        normal = compute_decay(1.0, 24.0, importance=0.3)
        important = compute_decay(1.0, 24.0, importance=0.9)
        assert important > normal

    def test_emotional_content_resists_decay(self):
        neutral = compute_decay(1.0, 24.0, valence=0.0)
        emotional = compute_decay(1.0, 24.0, valence=1.0)
        assert emotional > neutral

    def test_heat_approaches_zero(self):
        result = compute_decay(1.0, 1000.0)
        assert result < 0.01


class TestComputeSessionCoherence:
    def test_recent_memory_boosted(self):
        recent = datetime.now(timezone.utc).isoformat()
        result = compute_session_coherence(0.5, recent, bonus=0.2, window_hours=4.0)
        assert result > 0.5

    def test_old_memory_no_boost(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        result = compute_session_coherence(0.5, old, bonus=0.2, window_hours=4.0)
        assert result == 0.5

    def test_caps_at_one(self):
        recent = datetime.now(timezone.utc).isoformat()
        result = compute_session_coherence(0.95, recent, bonus=0.2)
        assert result <= 1.0

    def test_invalid_timestamp(self):
        assert compute_session_coherence(0.5, "not-a-date") == 0.5


class TestMetamemoryConfidence:
    def test_insufficient_data(self):
        assert compute_metamemory_confidence(2, 1) is None

    def test_all_useful(self):
        assert compute_metamemory_confidence(10, 10) == 1.0

    def test_half_useful(self):
        assert compute_metamemory_confidence(10, 5) == 0.5


class TestContentDetectors:
    def test_error_content_detected(self):
        assert is_error_content("There was an error in the build")
        assert is_error_content("Exception traceback")

    def test_non_error_content(self):
        assert not is_error_content("Everything is fine")

    def test_decision_content_detected(self):
        assert is_decision_content("We decided to use React")
        assert is_decision_content("Chose PostgreSQL over MySQL")

    def test_non_decision_content(self):
        assert not is_decision_content("The weather is nice")
