"""Tests for mcp_server.core.pattern_extractor — ported from pattern-extractor.test.js."""

from mcp_server.core.pattern_extractor import (
    extract_entry_points,
    extract_recurring_patterns,
    extract_session_shape,
    extract_tool_preferences,
)


# ---------------------------------------------------------------------------
# extract_entry_points
# ---------------------------------------------------------------------------


class TestExtractEntryPoints:
    def test_empty_input(self):
        assert extract_entry_points([]) == []

    def test_no_messages(self):
        assert extract_entry_points([{}, {"firstMessage": ""}]) == []

    def test_single_session(self):
        convs = [{"firstMessage": "Fix the authentication endpoint"}]
        result = extract_entry_points(convs)
        assert len(result) > 0
        assert result[0]["frequency"] == 1
        assert result[0]["confidence"] == 1
        assert len(result[0]["pattern"]) > 0
        assert isinstance(result[0]["exampleMessages"], list)

    def test_clusters_similar_messages(self):
        convs = [
            {"firstMessage": "Fix the authentication endpoint bug"},
            {"firstMessage": "Fix the authentication service error"},
            {"firstMessage": "Fix authentication module crash"},
            {"firstMessage": "Deploy the new pipeline to production"},
        ]
        result = extract_entry_points(convs)
        assert len(result) >= 1
        assert result[0]["frequency"] >= 2

    def test_limits_to_top_5(self):
        topics = [
            "implement database migrations system",
            "configure kubernetes deployment pipeline",
            "refactor authentication middleware layer",
            "design graphql schema definitions",
            "optimize elasticsearch query performance",
            "integrate stripe payment processing",
            "monitor prometheus alerting rules",
        ]
        convs = [{"firstMessage": t} for t in topics]
        result = extract_entry_points(convs)
        assert len(result) <= 5

    def test_reads_messages_array_fallback(self):
        convs = [
            {
                "messages": [
                    {"role": "user", "content": "Refactor the scanner module"},
                    {"role": "assistant", "content": "Sure, I will refactor it."},
                ],
            },
        ]
        result = extract_entry_points(convs)
        assert len(result) > 0

    def test_confidence_is_frequency_over_total(self):
        convs = [
            {"firstMessage": "Fix authentication endpoint issue"},
            {"firstMessage": "Fix authentication service problem"},
            {"firstMessage": "Deploy kubernetes production cluster"},
            {"firstMessage": "Deploy kubernetes staging environment"},
        ]
        result = extract_entry_points(convs)
        total_frequency = sum(ep["frequency"] for ep in result)
        assert total_frequency == 4


# ---------------------------------------------------------------------------
# extract_recurring_patterns
# ---------------------------------------------------------------------------


class TestExtractRecurringPatterns:
    def test_empty_input(self):
        assert extract_recurring_patterns([]) == []

    def test_fewer_than_3_sessions(self):
        convs = [
            {"allText": "implement feature something"},
            {"allText": "deploy pipeline another"},
        ]
        assert extract_recurring_patterns(convs) == []

    def test_empty_text(self):
        convs = [{"allText": ""}, {"allText": ""}, {"allText": ""}]
        assert extract_recurring_patterns(convs) == []

    def test_detects_patterns_in_3_plus_sessions(self):
        shared = "authentication middleware validation endpoint security"
        convs = [
            {"allText": f"Working on {shared} for the backend"},
            {"allText": f"Fixing {shared} in the service"},
            {"allText": f"Refactoring {shared} for performance"},
            {"allText": f"Testing {shared} coverage"},
        ]
        result = extract_recurring_patterns(convs)
        assert len(result) > 0
        assert result[0]["sessionsObserved"] >= 3
        assert result[0]["confidence"] > 0
        assert isinstance(result[0]["ngramSignature"], list)

    def test_confidence_calculation(self):
        phrase = "authentication middleware validation endpoint security"
        convs = [
            {"allText": f"Processing {phrase} system"},
            {"allText": f"Updating {phrase} system"},
            {"allText": f"Deploying {phrase} system"},
            {"allText": "something completely different unrelated"},
        ]
        result = extract_recurring_patterns(convs)
        if result:
            p = result[0]
            assert 0 < p["confidence"] <= 1
            assert p["confidence"] == p["sessionsObserved"] / len(convs)


# ---------------------------------------------------------------------------
# extract_tool_preferences
# ---------------------------------------------------------------------------


class TestExtractToolPreferences:
    def test_empty_input(self):
        assert extract_tool_preferences([]) == {}

    def test_string_tool_entries(self):
        convs = [
            {"toolsUsed": ["Read", "Read", "Edit"]},
            {"toolsUsed": ["Read", "Grep"]},
            {"toolsUsed": ["Bash"]},
        ]
        result = extract_tool_preferences(convs)
        assert abs(result["Read"]["ratio"] - 2 / 3) < 0.001
        assert abs(result["Read"]["avgPerSession"] - 1.5) < 0.001
        assert abs(result["Edit"]["ratio"] - 1 / 3) < 0.001
        assert abs(result["Edit"]["avgPerSession"] - 1) < 0.001

    def test_object_tool_entries(self):
        convs = [
            {"toolsUsed": [{"name": "Read", "count": 5}, {"name": "Edit", "count": 2}]},
            {"toolsUsed": [{"name": "Read", "count": 3}]},
        ]
        result = extract_tool_preferences(convs)
        assert abs(result["Read"]["ratio"] - 1.0) < 0.001
        assert abs(result["Read"]["avgPerSession"] - 4) < 0.001

    def test_tools_used_key_alternative(self):
        convs = [{"tools_used": ["Bash", "Bash", "Bash"]}]
        result = extract_tool_preferences(convs)
        assert result["Bash"]["ratio"] == 1
        assert result["Bash"]["avgPerSession"] == 3

    def test_sorted_by_ratio_descending(self):
        convs = [
            {"toolsUsed": ["Read"]},
            {"toolsUsed": ["Read"]},
            {"toolsUsed": ["Edit"]},
        ]
        result = extract_tool_preferences(convs)
        keys = list(result.keys())
        assert keys[0] == "Read"

    def test_ignores_non_array(self):
        convs = [{"toolsUsed": "not-an-array"}]
        assert extract_tool_preferences(convs) == {}


# ---------------------------------------------------------------------------
# extract_session_shape
# ---------------------------------------------------------------------------


class TestExtractSessionShape:
    def test_empty_input(self):
        result = extract_session_shape([])
        assert result["avgDuration"] == 0
        assert result["avgTurns"] == 0
        assert result["avgMessages"] == 0
        assert result["burstRatio"] == 0
        assert result["explorationRatio"] == 0
        assert result["dominantMode"] == "mixed"

    def test_burst_mode(self):
        convs = [
            {"duration": 300000, "turnCount": 5, "messageCount": 10},
            {"duration": 400000, "turnCount": 8, "messageCount": 15},
            {"duration": 200000, "turnCount": 3, "messageCount": 6},
        ]
        result = extract_session_shape(convs)
        assert result["dominantMode"] == "burst"
        assert result["burstRatio"] > 0.6
        assert result["avgDuration"] == 300000
        assert abs(result["avgTurns"] - 16 / 3) < 0.001

    def test_exploration_mode(self):
        convs = [
            {"duration": 1800000, "turnCount": 25, "messageCount": 50},
            {"duration": 2400000, "turnCount": 30, "messageCount": 60},
            {"duration": 3600000, "turnCount": 40, "messageCount": 80},
        ]
        result = extract_session_shape(convs)
        assert result["dominantMode"] == "exploration"
        assert result["explorationRatio"] > 0.6

    def test_mixed_mode(self):
        convs = [
            {"duration": 300000, "turnCount": 5, "messageCount": 10},
            {"duration": 1800000, "turnCount": 25, "messageCount": 50},
            {"duration": 900000, "turnCount": 15, "messageCount": 30},
        ]
        result = extract_session_shape(convs)
        assert result["dominantMode"] == "mixed"

    def test_duration_ms_fallback(self):
        convs = [{"durationMs": 300000, "turns": 5}]
        result = extract_session_shape(convs)
        assert result["avgDuration"] == 300000
        assert result["avgTurns"] == 5

    def test_messages_length_fallback(self):
        convs = [{"duration": 100000, "turnCount": 3, "messages": [1, 2, 3, 4, 5]}]
        result = extract_session_shape(convs)
        assert result["avgMessages"] == 5

    def test_missing_fields(self):
        convs = [{}, {}]
        result = extract_session_shape(convs)
        assert result["avgDuration"] == 0
        assert result["avgTurns"] == 0
        assert result["avgMessages"] == 0
