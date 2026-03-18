"""Tests for mcp_server.core.graph_builder — ported from graph-builder.test.js."""

from mcp_server.core.graph_builder import build_graph


def _make_profiles(domains=None):
    return {"domains": domains or {}}


def _make_domain_profile(**overrides):
    base = {
        "id": "test-domain",
        "label": "Test Domain",
        "projects": ["-Users-dev-test"],
        "confidence": 0.75,
        "sessionCount": 20,
        "entryPoints": [
            {"pattern": "fix / api / auth", "frequency": 5, "confidence": 0.8},
            {"pattern": "deploy / pipeline", "frequency": 3, "confidence": 0.4},
        ],
        "recurringPatterns": [
            {"pattern": "read before edit", "frequency": 8, "confidence": 0.6},
        ],
        "toolPreferences": {
            "Read": {"ratio": 0.9, "avgPerSession": 6},
            "Edit": {"ratio": 0.7, "avgPerSession": 4},
            "Grep": {"ratio": 0.5, "avgPerSession": 3},
        },
        "connectionBridges": [],
        "blindSpots": [
            {
                "type": "category",
                "value": "testing",
                "severity": "high",
                "description": "No testing",
                "suggestion": "Add tests",
            },
        ],
        "metacognitive": {},
        "sessionShape": {},
    }
    base.update(overrides)
    return base


class TestBuildGraph:
    def test_empty_profiles(self):
        result = build_graph(_make_profiles())
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["blindSpotRegions"] == []

    def test_creates_domain_hub(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain_profile(
                    label="Alpha", sessionCount=15, confidence=0.6
                ),
            }
        )
        result = build_graph(profiles)
        hubs = [n for n in result["nodes"] if n["type"] == "domain"]
        assert len(hubs) == 1
        assert hubs[0]["label"] == "Alpha"
        assert hubs[0]["domain"] == "alpha"
        assert hubs[0]["confidence"] == 0.6
        assert hubs[0]["sessionCount"] == 15
        assert hubs[0]["color"] == "#6366f1"
        assert hubs[0]["size"] >= 8

    def test_creates_entry_point_nodes(self):
        profiles = _make_profiles({"alpha": _make_domain_profile()})
        result = build_graph(profiles)
        eps = [n for n in result["nodes"] if n["type"] == "entry-point"]
        assert len(eps) == 2
        assert eps[0]["label"] == "fix / api / auth"
        assert eps[0]["domain"] == "alpha"
        assert eps[0]["color"] == "#00d4ff"
        assert eps[0]["frequency"] > 0

        ep_edges = [e for e in result["edges"] if e["type"] == "has-entry"]
        assert len(ep_edges) == 2
        hub = next(n for n in result["nodes"] if n["type"] == "domain")
        assert all(e["source"] == hub["id"] for e in ep_edges)

    def test_creates_recurring_pattern_nodes(self):
        profiles = _make_profiles({"alpha": _make_domain_profile()})
        result = build_graph(profiles)
        patterns = [n for n in result["nodes"] if n["type"] == "recurring-pattern"]
        assert len(patterns) == 1
        assert patterns[0]["label"] == "read before edit"
        assert patterns[0]["color"] == "#10b981"

        pattern_edges = [e for e in result["edges"] if e["type"] == "has-pattern"]
        assert len(pattern_edges) == 1

    def test_creates_tool_preference_nodes(self):
        profiles = _make_profiles({"alpha": _make_domain_profile()})
        result = build_graph(profiles)
        tools = [n for n in result["nodes"] if n["type"] == "tool-preference"]
        assert len(tools) == 3
        assert tools[0]["color"] == "#f59e0b"
        assert tools[0]["ratio"] > 0

        tool_edges = [e for e in result["edges"] if e["type"] == "uses-tool"]
        assert len(tool_edges) == 3

    def test_limits_tools_to_top_5(self):
        tools = {
            f"Tool{i}": {"ratio": (8 - i) / 10, "avgPerSession": i + 1}
            for i in range(8)
        }
        profiles = _make_profiles(
            {"alpha": _make_domain_profile(toolPreferences=tools)}
        )
        result = build_graph(profiles)
        tool_nodes = [n for n in result["nodes"] if n["type"] == "tool-preference"]
        assert len(tool_nodes) == 5

    def test_creates_bridge_edges(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain_profile(
                    connectionBridges=[
                        {"toDomain": "beta", "pattern": "structural-edge", "weight": 2}
                    ]
                ),
                "beta": _make_domain_profile(
                    connectionBridges=[
                        {"toDomain": "alpha", "pattern": "structural-edge", "weight": 2}
                    ]
                ),
            }
        )
        result = build_graph(profiles)
        bridge_edges = [e for e in result["edges"] if e["type"] == "bridge"]
        assert len(bridge_edges) >= 1
        assert bridge_edges[0]["weight"] > 0
        assert bridge_edges[0]["label"]

    def test_collects_blind_spot_regions(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain_profile(
                    blindSpots=[
                        {
                            "type": "category",
                            "value": "testing",
                            "severity": "high",
                            "description": "No testing",
                            "suggestion": "Add tests",
                        },
                        {
                            "type": "tool",
                            "value": "Grep",
                            "severity": "medium",
                            "description": "Low Grep usage",
                            "suggestion": "Use Grep",
                        },
                    ]
                ),
            }
        )
        result = build_graph(profiles)
        assert len(result["blindSpotRegions"]) == 2
        assert result["blindSpotRegions"][0]["domain"] == "alpha"
        assert result["blindSpotRegions"][0]["type"] == "category"
        assert result["blindSpotRegions"][0]["value"] == "testing"
        assert result["blindSpotRegions"][0]["severity"] == "high"

    def test_filter_domain(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain_profile(label="Alpha"),
                "beta": _make_domain_profile(label="Beta"),
            }
        )
        result = build_graph(profiles, "alpha")
        domains = [n for n in result["nodes"] if n["type"] == "domain"]
        assert len(domains) == 1
        assert domains[0]["label"] == "Alpha"
        for node in result["nodes"]:
            assert node["domain"] == "alpha"

    def test_filter_nonexistent_domain(self):
        profiles = _make_profiles({"alpha": _make_domain_profile()})
        result = build_graph(profiles, "nonexistent")
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["blindSpotRegions"] == []

    def test_unique_node_ids(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain_profile(),
                "beta": _make_domain_profile(),
            }
        )
        result = build_graph(profiles)
        ids = [n["id"] for n in result["nodes"]]
        assert len(ids) == len(set(ids))

    def test_empty_domain(self):
        profiles = _make_profiles(
            {
                "empty": _make_domain_profile(
                    entryPoints=[],
                    recurringPatterns=[],
                    toolPreferences={},
                    connectionBridges=[],
                    blindSpots=[],
                ),
            }
        )
        result = build_graph(profiles)
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["type"] == "domain"
        assert result["blindSpotRegions"] == []

    def test_multiple_domains(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain_profile(label="Alpha"),
                "beta": _make_domain_profile(label="Beta"),
                "gamma": _make_domain_profile(label="Gamma"),
            }
        )
        result = build_graph(profiles)
        hubs = [n for n in result["nodes"] if n["type"] == "domain"]
        assert len(hubs) == 3
        labels = sorted(h["label"] for h in hubs)
        assert labels == ["Alpha", "Beta", "Gamma"]

    def test_hub_size_scales(self):
        profiles = _make_profiles(
            {
                "small": _make_domain_profile(sessionCount=1),
                "large": _make_domain_profile(sessionCount=50),
            }
        )
        result = build_graph(profiles)
        small = next(
            n
            for n in result["nodes"]
            if n["type"] == "domain" and n["sessionCount"] == 1
        )
        large = next(
            n
            for n in result["nodes"]
            if n["type"] == "domain" and n["sessionCount"] == 50
        )
        assert large["size"] > small["size"]

    def test_hub_size_clamped(self):
        profiles = _make_profiles(
            {
                "tiny": _make_domain_profile(sessionCount=0),
                "huge": _make_domain_profile(sessionCount=1000),
            }
        )
        result = build_graph(profiles)
        for n in result["nodes"]:
            if n["type"] == "domain":
                assert 8 <= n["size"] <= 30
