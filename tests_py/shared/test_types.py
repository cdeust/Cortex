"""Tests for mcp_server.shared.types — Pydantic model validation."""

import json

from mcp_server.shared.types_profiles import (
    DomainProfile,
    GlobalStyle,
    ProfilesV2,
    SessionLogEntry,
)


class TestProfilesV2:
    def test_empty_profiles(self):
        p = ProfilesV2(version=2, domains={})
        assert p.version == 2
        assert p.domains == {}

    def test_roundtrip_serialization(self):
        """Profiles can be serialized to JSON and back without loss."""
        p = ProfilesV2(
            version=2,
            updatedAt="2025-01-01T00:00:00Z",
            globalStyle=GlobalStyle(
                activeReflective=0.5,
                sensingIntuitive=-0.3,
                sequentialGlobal=0.1,
                confidence=0.8,
                sessionCount=50,
            ),
            domains={
                "jarvis": DomainProfile(
                    id="jarvis",
                    label="Jarvis",
                    projects=["-Users-dev-jarvis"],
                    categories={"feature": 0.6, "bug-fix": 0.4},
                    topKeywords=["api", "authentication"],
                    sessionCount=10,
                    confidence=0.85,
                )
            },
        )
        data = json.loads(p.model_dump_json(by_alias=True))
        p2 = ProfilesV2.model_validate(data)
        assert p2.version == 2
        assert "jarvis" in p2.domains
        assert p2.domains["jarvis"].session_count == 10

    def test_loads_js_format_json(self):
        """Can parse JSON in the format the JS server writes."""
        js_json = {
            "version": 2,
            "updatedAt": "2025-03-15T10:30:00Z",
            "globalStyle": {
                "activeReflective": 0.7,
                "sensingIntuitive": -0.2,
                "sequentialGlobal": 0.3,
                "confidence": 0.9,
                "sessionCount": 100,
            },
            "domains": {
                "web-app": {
                    "id": "web-app",
                    "label": "Web App",
                    "projects": ["-Users-dev-webapp"],
                    "categories": {"feature": 0.5},
                    "topKeywords": ["react", "api"],
                    "entryPoints": [
                        {
                            "pattern": "react / component",
                            "frequency": 5,
                            "confidence": 0.5,
                            "exampleMessages": ["build a form"],
                        }
                    ],
                    "recurringPatterns": [
                        {
                            "pattern": "test after",
                            "ngramSignature": ["test", "after"],
                            "frequency": 3,
                            "sessionsObserved": 3,
                            "confidence": 0.3,
                        }
                    ],
                    "toolPreferences": {"Read": {"ratio": 0.8, "avgPerSession": 5.2}},
                    "sessionShape": {
                        "avgDuration": 300000,
                        "avgTurns": 15,
                        "avgMessages": 30,
                        "burstRatio": 0.3,
                        "explorationRatio": 0.2,
                        "dominantMode": "mixed",
                    },
                    "connectionBridges": [
                        {
                            "toDomain": "api",
                            "pattern": "structural-edge",
                            "weight": 0.7,
                            "examples": [],
                            "edgeCount": 3,
                        }
                    ],
                    "blindSpots": [
                        {
                            "type": "category",
                            "value": "testing",
                            "severity": "high",
                            "description": "No testing sessions",
                            "suggestion": "Try writing tests",
                        }
                    ],
                    "metacognitive": {
                        "activeReflective": 0.5,
                        "sensingIntuitive": -0.3,
                        "sequentialGlobal": 0.1,
                        "problemDecomposition": "top-down",
                        "explorationStyle": "depth-first",
                        "verificationBehavior": "test-after",
                    },
                    "confidence": 0.85,
                    "sessionCount": 10,
                    "lastUpdated": "2025-03-15T10:30:00Z",
                    "firstSeen": "2025-01-01T00:00:00Z",
                }
            },
        }
        p = ProfilesV2.model_validate(js_json)
        assert p.version == 2
        assert p.global_style is not None
        assert p.global_style.active_reflective == 0.7

        d = p.domains["web-app"]
        assert d.label == "Web App"
        assert d.session_count == 10
        assert len(d.entry_points) == 1
        assert d.entry_points[0].pattern == "react / component"
        assert len(d.recurring_patterns) == 1
        assert d.tool_preferences["Read"].ratio == 0.8
        assert d.session_shape is not None
        assert d.session_shape.dominant_mode == "mixed"
        assert len(d.connection_bridges) == 1
        assert len(d.blind_spots) == 1
        assert d.metacognitive is not None
        assert d.metacognitive.verification_behavior == "test-after"

    def test_extra_fields_ignored(self):
        """Unknown fields in JSON don't cause validation errors."""
        data = {
            "version": 2,
            "updatedAt": None,
            "globalStyle": None,
            "domains": {},
            "futureField": "should be ignored",
        }
        p = ProfilesV2.model_validate(data)
        assert p.version == 2


class TestSessionLogEntry:
    def test_parses_js_format(self):
        data = {
            "sessionId": "abc123",
            "domain": "web",
            "timestamp": "2025-03-15T10:00:00Z",
            "project": "-Users-dev-web",
            "cwd": "/Users/dev/web",
            "duration": 60000,
            "turnCount": 10,
            "toolsUsed": ["Read", "Edit"],
            "category": "feature",
            "entryKeywords": ["api", "auth"],
        }
        entry = SessionLogEntry.model_validate(data)
        assert entry.session_id == "abc123"
        assert entry.turn_count == 10
        assert entry.tools_used == ["Read", "Edit"]
