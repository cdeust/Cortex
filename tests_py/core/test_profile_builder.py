"""Tests for mcp_server.core.profile_builder — ported from profile-builder.test.js."""

import re

from mcp_server.core.profile_assembler import build_domain_profiles
from mcp_server.core.profile_builder import apply_session_update


def _make_conversation(**overrides):
    base = {
        "firstMessage": "Fix the authentication bug",
        "allText": "Fix the authentication bug in the login endpoint",
        "toolsUsed": ["Read", "Edit", "Bash"],
        "turnCount": 8,
        "duration": 300000,
        "durationMinutes": 5,
        "messageCount": 16,
        "keywords": {"authentication", "endpoint"},
        "startedAt": "2025-01-15T10:00:00Z",
        "endedAt": "2025-01-15T10:05:00Z",
    }
    base.update(overrides)
    return base


def _empty_profiles():
    return {"domains": {}}


def _by_project(project_id, conversations):
    return {project_id: conversations}


class TestBuildDomainProfiles:
    def test_creates_domain_from_conversations(self):
        convs = [
            _make_conversation(),
            _make_conversation(
                firstMessage="Refactor the scanner module",
                allText="Refactor the scanner module for clarity",
            ),
            _make_conversation(
                firstMessage="Add new feature endpoint",
                allText="Add new feature endpoint for the API",
            ),
        ]
        result = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=convs,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-cortex", convs),
        )
        assert result.get("domains")
        domain_ids = list(result["domains"].keys())
        assert len(domain_ids) > 0

        domain = result["domains"][domain_ids[0]]
        assert domain["sessionCount"] == 3
        assert domain.get("label")
        assert isinstance(domain["projects"], list)
        assert "-Users-dev-cortex" in domain["projects"]
        assert isinstance(domain["entryPoints"], list)
        assert domain.get("toolPreferences") is not None
        assert domain.get("sessionShape") is not None
        assert domain.get("metacognitive") is not None
        assert isinstance(domain["blindSpots"], list)
        assert isinstance(domain["connectionBridges"], list)
        assert domain.get("topKeywords") is not None
        assert domain.get("categories") is not None

    def test_confidence_scales_with_sessions(self):
        few = [_make_conversation()]
        r1 = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=few,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-proj", few),
        )
        many = [_make_conversation() for _ in range(50)]
        r2 = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=many,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-proj2", many),
        )
        d1 = list(r1["domains"].values())[0]
        d2 = list(r2["domains"].values())[0]
        assert d2["confidence"] > d1["confidence"]

    def test_sets_global_style(self):
        convs = [_make_conversation() for _ in range(10)]
        result = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=convs,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-proj", convs),
        )
        gs = result.get("globalStyle")
        assert gs is not None
        assert "activeReflective" in gs
        assert "sensingIntuitive" in gs
        assert "sequentialGlobal" in gs
        assert "confidence" in gs
        assert gs["sessionCount"] == 10

    def test_preserves_existing_domains(self):
        existing = {
            "domains": {
                "existing-domain": {
                    "id": "existing-domain",
                    "label": "Existing",
                    "projects": ["-Users-dev-existing"],
                    "sessionCount": 5,
                },
            },
        }
        new_convs = [_make_conversation()]
        result = build_domain_profiles(
            existing_profiles=existing,
            conversations=new_convs,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-newproj", new_convs),
        )
        assert "existing-domain" in result["domains"]
        assert len(result["domains"]) >= 2

    def test_target_domain_filter(self):
        convs_a = [_make_conversation()]
        convs_b = [_make_conversation()]
        existing = _empty_profiles()
        existing["domains"]["cortex"] = {
            "projects": ["-Users-dev-cortex"],
            "sessionCount": 0,
        }
        existing["domains"]["other"] = {
            "projects": ["-Users-dev-other"],
            "sessionCount": 0,
        }

        result = build_domain_profiles(
            existing_profiles=existing,
            conversations=[*convs_a, *convs_b],
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project={"-Users-dev-cortex": convs_a, "-Users-dev-other": convs_b},
            target_domain="cortex",
        )
        assert result["domains"]["cortex"]["sessionCount"] == 1
        assert result["domains"]["other"]["sessionCount"] == 0

    def test_empty_by_project(self):
        result = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=[],
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project={},
        )
        assert result["domains"] == {}

    def test_records_timestamps(self):
        convs = [
            _make_conversation(startedAt="2025-01-10T00:00:00Z"),
            _make_conversation(startedAt="2025-01-20T00:00:00Z"),
        ]
        result = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=convs,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-proj", convs),
        )
        domain = list(result["domains"].values())[0]
        assert domain["firstSeen"] == "2025-01-10T00:00:00Z"
        assert domain["lastUpdated"] == "2025-01-20T00:00:00Z"

    def test_builds_category_distribution(self):
        convs = [
            _make_conversation(
                allText="fix the bug in the broken code crash error regression"
            )
            for _ in range(5)
        ]
        result = build_domain_profiles(
            existing_profiles=_empty_profiles(),
            conversations=convs,
            memories={},
            brain_index={"memories": {}, "conversations": {}},
            by_project=_by_project("-Users-dev-proj", convs),
        )
        domain = list(result["domains"].values())[0]
        assert domain.get("categories")
        assert len(domain["categories"]) > 0


class TestApplySessionUpdate:
    def _make_domain_profile(self):
        return {
            "sessionCount": 10,
            "confidence": 0.2,
            "sessionShape": {
                "avgDuration": 500000,
                "avgTurns": 12,
                "avgMessages": 24,
                "burstRatio": 0.5,
                "explorationRatio": 0.3,
                "dominantMode": "mixed",
            },
            "toolPreferences": {
                "Read": {"ratio": 0.8, "avgPerSession": 5},
                "Edit": {"ratio": 0.6, "avgPerSession": 3},
            },
            "metacognitive": {
                "activeReflective": 0.3,
                "sensingIntuitive": -0.2,
                "sequentialGlobal": 0.1,
                "problemDecomposition": "top-down",
                "explorationStyle": "depth-first",
                "verificationBehavior": "test-after",
            },
        }

    def test_increments_session_count(self):
        dp = self._make_domain_profile()
        result = apply_session_update(
            domain_profile=dp,
            session_data={"duration": 300000, "tools_used": ["Read"], "turn_count": 5},
        )
        assert result["sessionCount"] == 11

    def test_updates_session_shape_avg(self):
        dp = self._make_domain_profile()
        old_avg = dp["sessionShape"]["avgDuration"]
        new_dur = 200000
        apply_session_update(
            domain_profile=dp,
            session_data={"duration": new_dur, "tools_used": [], "turn_count": 5},
        )
        expected = old_avg + (new_dur - old_avg) / 11
        assert abs(dp["sessionShape"]["avgDuration"] - expected) < 1

    def test_updates_burst_ratio(self):
        dp = self._make_domain_profile()
        old_burst = dp["sessionShape"]["burstRatio"]
        apply_session_update(
            domain_profile=dp,
            session_data={"duration": 300000, "tools_used": [], "turn_count": 5},
        )
        expected = old_burst + (1 - old_burst) / 11
        assert abs(dp["sessionShape"]["burstRatio"] - expected) < 0.001

    def test_updates_tool_preferences_existing(self):
        dp = self._make_domain_profile()
        apply_session_update(
            domain_profile=dp,
            session_data={
                "duration": 300000,
                "tools_used": ["Read", "Read", "Read"],
                "turn_count": 5,
            },
        )
        assert abs(dp["toolPreferences"]["Read"]["ratio"] - 9 / 11) < 0.01

    def test_adds_new_tool(self):
        dp = self._make_domain_profile()
        apply_session_update(
            domain_profile=dp,
            session_data={
                "duration": 300000,
                "tools_used": ["Grep", "Grep"],
                "turn_count": 5,
            },
        )
        assert "Grep" in dp["toolPreferences"]
        assert abs(dp["toolPreferences"]["Grep"]["ratio"] - 1 / 11) < 0.01
        assert dp["toolPreferences"]["Grep"]["avgPerSession"] == 2

    def test_decreases_unused_tool_ratio(self):
        dp = self._make_domain_profile()
        old_edit = dp["toolPreferences"]["Edit"]["ratio"]
        apply_session_update(
            domain_profile=dp,
            session_data={"duration": 300000, "tools_used": ["Read"], "turn_count": 5},
        )
        assert dp["toolPreferences"]["Edit"]["ratio"] < old_edit

    def test_updates_confidence(self):
        dp = self._make_domain_profile()
        apply_session_update(
            domain_profile=dp,
            session_data={"duration": 300000, "tools_used": [], "turn_count": 5},
        )
        assert dp["confidence"] == 0.22

    def test_sets_last_updated(self):
        dp = self._make_domain_profile()
        apply_session_update(
            domain_profile=dp,
            session_data={"duration": 300000, "tools_used": [], "turn_count": 5},
        )
        assert dp.get("lastUpdated")
        assert re.match(r"^\d{4}-\d{2}-\d{2}T", dp["lastUpdated"])

    def test_style_ema_update(self):
        dp = self._make_domain_profile()
        old_ar = dp["metacognitive"]["activeReflective"]
        apply_session_update(
            domain_profile=dp,
            session_data={
                "duration": 300000,
                "tools_used": ["Edit", "Edit", "Edit", "Write", "Read"],
                "turn_count": 5,
            },
        )
        assert dp["metacognitive"]["activeReflective"] != old_ar

    def test_recalculates_dominant_mode(self):
        dp = self._make_domain_profile()
        dp["sessionShape"]["burstRatio"] = 0.59
        dp["sessionShape"]["explorationRatio"] = 0.1
        dp["sessionCount"] = 1
        apply_session_update(
            domain_profile=dp,
            session_data={"duration": 100000, "tools_used": [], "turn_count": 3},
        )
        assert dp["sessionShape"]["dominantMode"] == "burst"
