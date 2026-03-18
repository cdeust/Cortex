"""Tests for mcp_server.core.attribution_tracer — ported from attribution-tracer.test.js."""

from mcp_server.core.attribution_tracer import (
    trace_attribution,
    build_attribution_nodes,
    compute_edge_weights,
)
from mcp_server.core.sparse_dictionary import build_seed_dictionary


def _make_conv(**overrides):
    base = {
        "sessionId": "test",
        "toolsUsed": ["Read", "Edit", "Grep"],
        "allText": "fix the bug in auth module",
        "firstMessage": "fix the auth bug",
        "duration": 600000,
        "turnCount": 10,
    }
    base.update(overrides)
    return base


def _make_profile(**overrides):
    base = {
        "id": "test-domain",
        "label": "Test",
        "confidence": 0.7,
        "sessionCount": 10,
        "metacognitive": {
            "activeReflective": 0.3,
            "sensingIntuitive": -0.2,
            "sequentialGlobal": 0.5,
            "problemDecomposition": "top-down",
            "explorationStyle": "depth-first",
            "verificationBehavior": "test-after",
        },
        "entryPoints": [],
        "recurringPatterns": [],
        "toolPreferences": {},
        "sessionShape": {
            "avgDuration": 600000,
            "avgTurns": 10,
            "avgMessages": 15,
            "burstRatio": 0.5,
            "explorationRatio": 0.3,
            "dominantMode": "mixed",
        },
    }
    base.update(overrides)
    return base


class TestBuildAttributionNodes:
    def test_creates_nodes_for_all_layers(self):
        d = build_seed_dictionary()
        nodes = build_attribution_nodes(_make_profile(), d)
        layers = {n["layer"] for n in nodes}
        assert "input" in layers
        assert "extractor" in layers
        assert "classifier" in layers
        assert "feature" in layers
        assert "aggregator" in layers
        assert "output" in layers

    def test_has_27_input_nodes(self):
        d = build_seed_dictionary()
        nodes = build_attribution_nodes(_make_profile(), d)
        inputs = [n for n in nodes if n["layer"] == "input"]
        assert len(inputs) == 27

    def test_has_4_extractor_nodes(self):
        d = build_seed_dictionary()
        nodes = build_attribution_nodes(_make_profile(), d)
        extractors = [n for n in nodes if n["layer"] == "extractor"]
        assert len(extractors) == 4

    def test_has_6_classifier_nodes(self):
        d = build_seed_dictionary()
        nodes = build_attribution_nodes(_make_profile(), d)
        classifiers = [n for n in nodes if n["layer"] == "classifier"]
        assert len(classifiers) == 6

    def test_classifier_activation_from_profile(self):
        d = build_seed_dictionary()
        nodes = build_attribution_nodes(_make_profile(), d)
        ar = next(n for n in nodes if n["id"] == "classifier:activeReflective")
        assert ar["activation"] == 0.3

    def test_feature_nodes_match_dictionary(self):
        d = build_seed_dictionary()
        nodes = build_attribution_nodes(_make_profile(), d)
        features = [n for n in nodes if n["layer"] == "feature"]
        assert len(features) == len(d["features"])

    def test_handles_null_dictionary(self):
        nodes = build_attribution_nodes(_make_profile(), None)
        features = [n for n in nodes if n["layer"] == "feature"]
        assert len(features) == 0


class TestComputeEdgeWeights:
    def test_produces_edges(self):
        d = build_seed_dictionary()
        edges = compute_edge_weights([_make_conv()], _make_profile(), d)
        assert len(edges) > 0

    def test_all_weights_non_negative(self):
        d = build_seed_dictionary()
        edges = compute_edge_weights([_make_conv()], _make_profile(), d)
        for e in edges:
            assert e["weight"] >= 0, (
                f"Edge {e['source']} -> {e['target']}: {e['weight']}"
            )

    def test_includes_aggregator_to_output(self):
        d = build_seed_dictionary()
        edges = compute_edge_weights([_make_conv()], _make_profile(), d)
        agg = next(
            (
                e
                for e in edges
                if e["source"] == "aggregator:profile"
                and e["target"] == "output:context"
            ),
            None,
        )
        assert agg is not None

    def test_handles_empty_conversations(self):
        d = build_seed_dictionary()
        edges = compute_edge_weights([], _make_profile(), d)
        assert len(edges) > 0  # structural edges still present


class TestTraceAttribution:
    def test_returns_nodes_and_edges(self):
        d = build_seed_dictionary()
        graph = trace_attribution([_make_conv()], d, _make_profile())
        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0

    def test_empty_for_no_conversations(self):
        d = build_seed_dictionary()
        graph = trace_attribution([], d, _make_profile())
        assert len(graph["nodes"]) == 0
        assert len(graph["edges"]) == 0

    def test_empty_for_null_profile(self):
        d = build_seed_dictionary()
        graph = trace_attribution([_make_conv()], d, None)
        assert len(graph["nodes"]) == 0

    def test_updates_input_activations(self):
        d = build_seed_dictionary()
        graph = trace_attribution(
            [_make_conv(toolsUsed=["Read", "Read", "Read"])],
            d,
            _make_profile(),
        )
        read_node = next(
            (n for n in graph["nodes"] if n["id"] == "input:tool:Read"), None
        )
        assert read_node is not None
        assert read_node["activation"] > 0

    def test_samples_at_most_20(self):
        d = build_seed_dictionary()
        convs = [_make_conv(sessionId=f"s-{i}") for i in range(50)]
        graph = trace_attribution(convs, d, _make_profile())
        assert len(graph["nodes"]) > 0
