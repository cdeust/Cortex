"""Tests for mcp_server.handlers.query_methodology — ported from
query-methodology.test.js."""

import asyncio
from unittest.mock import patch

from mcp_server.handlers.query_methodology import handler


class TestQueryMethodologyHandler:
    def test_response_shape_no_args(self):
        result = asyncio.run(handler())
        assert result is not None
        assert "domain" in result
        assert "confidence" in result
        assert "coldStart" in result
        assert "context" in result
        assert isinstance(result["context"], str)
        assert "entryPoints" in result
        assert isinstance(result["entryPoints"], list)
        assert "recurringPatterns" in result
        assert isinstance(result["recurringPatterns"], list)
        assert "toolPreferences" in result
        assert "blindSpots" in result
        assert isinstance(result["blindSpots"], list)
        assert "connectionBridges" in result
        assert "sessionCount" in result
        assert isinstance(result["sessionCount"], (int, float))
        # Memory integration fields
        assert "hotMemories" in result
        assert isinstance(result["hotMemories"], list)
        assert "firedTriggers" in result
        assert isinstance(result["firedTriggers"], list)

    def test_response_shape_with_cwd(self):
        result = asyncio.run(handler({"cwd": "/tmp/test-project"}))
        assert result is not None
        assert "domain" in result
        assert "context" in result

    def test_response_shape_with_project(self):
        result = asyncio.run(handler({"project": "test-project"}))
        assert result is not None
        assert "confidence" in result
        assert isinstance(result["confidence"], (int, float))


class TestCrossPlatformDomainResolution:
    """Issue #18 (PSGSupport): Windows cwd should resolve to the matching domain.

    The slug Claude Code stores for `C:\\Users\\michael.crawford` is
    `c--users-michael-crawford`. A populated profile keyed by that slug must
    materialize all body fields (style, entryPoints, recurringPatterns,
    blindSpots) regardless of how the user expresses the cwd.
    """

    @staticmethod
    def _populated_profile() -> dict:
        return {
            "id": "c--users-michael-crawford",
            "label": "Michael Crawford Workspace",
            "projects": ["c--users-michael-crawford"],
            "categories": {"general": 1.0},
            "topKeywords": ["windows", "psgsupport"],
            "entryPoints": [{"label": "ad-hoc query", "ratio": 0.5}],
            "recurringPatterns": [{"pattern": "checks logs first", "frequency": 3}],
            "toolPreferences": {"Read": {"ratio": 0.8, "avgPerSession": 4}},
            "sessionShape": {
                "avgDuration": 1000,
                "avgTurns": 5,
                "burstRatio": 0.5,
                "explorationRatio": 0.5,
                "dominantMode": "mixed",
            },
            "connectionBridges": [],
            "blindSpots": [{"category": "tests", "gap": "no test runs observed"}],
            "metacognitive": {
                "activeReflective": -0.3,
                "sensingIntuitive": 0.0,
                "sequentialGlobal": 0.1,
                "problemDecomposition": "bottom-up",
                "explorationStyle": "depth-first",
                "verificationBehavior": "no-test",
            },
            "confidence": 0.8,
            "sessionCount": 50,
            "lastUpdated": "2026-05-01T00:00:00Z",
            "firstSeen": "2026-04-01T00:00:00Z",
        }

    def _fake_profiles(self) -> dict:
        return {
            "version": 2,
            "updatedAt": "2026-05-01T00:00:00Z",
            "globalStyle": None,
            "domains": {"c--users-michael-crawford": self._populated_profile()},
        }

    def _run(self, args: dict) -> dict:
        # Patch the symbol where it's looked up (the handler imports it
        # at module load time; patching the handler module's binding is
        # what matters, not the source module).
        with patch(
            "mcp_server.handlers.query_methodology.load_profiles",
            return_value=self._fake_profiles(),
        ):
            return asyncio.run(handler(args))

    def test_windows_forward_slash_cwd_resolves_to_domain(self):
        result = self._run({"cwd": "C:/Users/michael.crawford"})
        assert result["domain"] == "c--users-michael-crawford"
        assert result["coldStart"] is False

    def test_windows_backslash_cwd_resolves_to_domain(self):
        result = self._run({"cwd": "C:\\Users\\michael.crawford"})
        assert result["domain"] == "c--users-michael-crawford"

    def test_gitbash_cwd_resolves_to_domain(self):
        result = self._run({"cwd": "/c/users/michael.crawford"})
        assert result["domain"] == "c--users-michael-crawford"

    def test_profile_body_fields_populate_when_resolved(self):
        # Secondary issue: even when the domain resolves and hotMemories
        # populate, the body fields must materialize from the on-disk profile.
        result = self._run({"project": "c--users-michael-crawford"})
        assert result["domain"] == "c--users-michael-crawford"
        assert result["coldStart"] is False
        assert result["style"] is not None
        assert result["entryPoints"] != []
        assert result["recurringPatterns"] != []
        assert result["blindSpots"] != []
        assert result["sessionCount"] == 50
