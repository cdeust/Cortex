"""Tests for mcp_server.core.emotional_tagging — amygdala-inspired encoding."""

import pytest

from mcp_server.core.emotional_tagging import (
    detect_emotions,
    compute_arousal,
    compute_emotional_valence,
    compute_importance_boost,
    compute_decay_resistance,
    tag_memory_emotions,
)


class TestDetectEmotions:
    def test_frustration(self):
        e = detect_emotions("Spent hours debugging this nightmare, still broken")
        assert e["frustration"] > 0

    def test_satisfaction(self):
        e = detect_emotions(
            "Finally got it working, this solution is elegant and beautiful"
        )
        assert e["satisfaction"] > 0

    def test_confusion(self):
        e = detect_emotions("Why does this make no sense? Bizarre behavior")
        assert e["confusion"] > 0

    def test_urgency(self):
        e = detect_emotions("CRITICAL: production is down, need hotfix ASAP")
        assert e["urgency"] > 0

    def test_discovery(self):
        e = detect_emotions("Turns out the key finding is that realized this insight")
        assert e["discovery"] > 0

    def test_neutral_content(self):
        e = detect_emotions("Updated the README with new installation instructions")
        total = sum(e.values())
        assert total < 0.5

    def test_multiple_emotions(self):
        e = detect_emotions("Finally fixed that nightmare bug after hours of struggle")
        assert e["satisfaction"] > 0
        assert e["frustration"] > 0

    def test_capped_at_one(self):
        e = detect_emotions(
            "frustrating frustrating frustrating frustrating frustrating"
        )
        assert e["frustration"] <= 1.0


class TestArousal:
    def test_no_emotions(self):
        assert compute_arousal({"frustration": 0, "satisfaction": 0}) == 0.0

    def test_single_emotion(self):
        a = compute_arousal({"frustration": 0.8, "satisfaction": 0})
        assert 0 < a <= 1.0

    def test_multiple_emotions_boost(self):
        a1 = compute_arousal({"frustration": 0.5, "satisfaction": 0, "urgency": 0})
        a2 = compute_arousal({"frustration": 0.5, "satisfaction": 0.5, "urgency": 0.5})
        assert a2 >= a1


class TestValence:
    def test_positive(self):
        v = compute_emotional_valence(
            {
                "satisfaction": 0.8,
                "frustration": 0,
                "confusion": 0,
                "urgency": 0,
                "discovery": 0.5,
            }
        )
        assert v > 0

    def test_negative(self):
        v = compute_emotional_valence(
            {
                "satisfaction": 0,
                "frustration": 0.8,
                "confusion": 0,
                "urgency": 0.5,
                "discovery": 0,
            }
        )
        assert v < 0

    def test_neutral(self):
        v = compute_emotional_valence(
            {
                "frustration": 0,
                "satisfaction": 0,
                "confusion": 0,
                "urgency": 0,
                "discovery": 0,
            }
        )
        assert v == 0.0

    def test_bounded(self):
        v = compute_emotional_valence(
            {
                "satisfaction": 1.0,
                "frustration": 0,
                "confusion": 0,
                "urgency": 0,
                "discovery": 1.0,
            }
        )
        assert -1.0 <= v <= 1.0


class TestImportanceBoost:
    def test_no_emotion_baseline(self):
        emotions = {
            "frustration": 0,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 0,
            "discovery": 0,
        }
        boost = compute_importance_boost(emotions, 0.0)
        assert boost == 1.0

    def test_moderate_arousal_boosts(self):
        emotions = {
            "frustration": 0.5,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 0,
            "discovery": 0,
        }
        boost = compute_importance_boost(emotions, 0.5)
        assert boost > 1.0

    def test_urgency_bonus(self):
        base_emotions = {
            "frustration": 0,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 0,
            "discovery": 0,
        }
        urgent_emotions = {
            "frustration": 0,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 1.0,
            "discovery": 0,
        }
        b1 = compute_importance_boost(base_emotions, 0.5)
        b2 = compute_importance_boost(urgent_emotions, 0.5)
        assert b2 > b1

    def test_yerkes_dodson_peak(self):
        e = {
            "frustration": 0,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 0,
            "discovery": 0,
        }
        low = compute_importance_boost(e, 0.2)
        mid = compute_importance_boost(e, 0.7)
        high = compute_importance_boost(e, 1.0)
        assert mid > low  # Moderate > low
        assert mid >= high  # Peak at moderate

    def test_bounded(self):
        e = {
            "urgency": 1.0,
            "discovery": 1.0,
            "frustration": 1.0,
            "satisfaction": 1.0,
            "confusion": 1.0,
        }
        assert compute_importance_boost(e, 1.0) <= 2.0


class TestDecayResistance:
    def test_no_emotion_baseline(self):
        e = {
            "frustration": 0,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 0,
            "discovery": 0,
        }
        assert compute_decay_resistance(e, 0.0) == 1.0

    def test_emotional_resists_decay(self):
        e = {
            "frustration": 0.8,
            "satisfaction": 0,
            "confusion": 0,
            "urgency": 0,
            "discovery": 0,
        }
        r = compute_decay_resistance(e, 0.8)
        assert r > 1.0

    def test_bounded(self):
        e = {
            "urgency": 1.0,
            "discovery": 1.0,
            "frustration": 1.0,
            "satisfaction": 1.0,
            "confusion": 1.0,
        }
        assert compute_decay_resistance(e, 1.0) <= 2.0


class TestTagMemoryEmotions:
    def test_emotional_content(self):
        result = tag_memory_emotions(
            "Finally fixed that critical production outage after hours of struggle!"
        )
        assert result["is_emotional"]
        assert result["arousal"] > 0.2
        assert result["importance_boost"] > 1.0
        assert result["decay_resistance"] > 1.0
        assert "emotions" in result
        assert "dominant_emotion" in result

    def test_neutral_content(self):
        result = tag_memory_emotions("Updated the config file with new settings")
        assert not result["is_emotional"]
        assert result["importance_boost"] == pytest.approx(1.0, abs=0.1)
        assert result["dominant_emotion"] == "neutral"

    def test_returns_all_fields(self):
        result = tag_memory_emotions("test content")
        assert "emotions" in result
        assert "arousal" in result
        assert "valence" in result
        assert "importance_boost" in result
        assert "decay_resistance" in result
        assert "is_emotional" in result
        assert "dominant_emotion" in result
