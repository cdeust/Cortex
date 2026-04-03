"""Tests for discussion node construction."""

from __future__ import annotations

from mcp_server.core.graph_builder_discussions import (
    DISCUSSION_COLOR,
    build_discussion_node,
    build_discussion_nodes,
)


def _make_conv(**overrides) -> dict:
    """Create a minimal conversation dict with sensible defaults."""
    base = {
        "sessionId": "sess-001",
        "project": "-Users-dev-MyProject",
        "firstMessage": "Fix the login bug",
        "startedAt": "2026-01-15T10:00:00Z",
        "endedAt": "2026-01-15T10:30:00Z",
        "duration": 1_800_000,
        "turnCount": 12,
        "messageCount": 24,
        "toolsUsed": ["Read", "Edit", "Bash"],
        "keywords": ["login", "bug", "auth"],
        "fileSize": 50000,
    }
    base.update(overrides)
    return base


class TestBuildDiscussionNode:
    def test_produces_correct_structure(self):
        conv = _make_conv()
        node = build_discussion_node(conv, "disc_1")

        assert node["id"] == "disc_1"
        assert node["type"] == "discussion"
        assert node["color"] == DISCUSSION_COLOR
        assert node["sessionId"] == "sess-001"
        assert node["turnCount"] == 12
        assert node["messageCount"] == 24
        assert node["toolsUsed"] == ["Read", "Edit", "Bash"]
        assert node["domain"] == "-Users-dev-MyProject"
        assert node["group"] == "-Users-dev-MyProject"

    def test_label_truncated_to_50_chars(self):
        long_msg = "A" * 80
        conv = _make_conv(firstMessage=long_msg)
        node = build_discussion_node(conv, "disc_1")

        assert node["label"] == "A" * 50 + "..."

    def test_label_not_truncated_when_short(self):
        conv = _make_conv(firstMessage="Short msg")
        node = build_discussion_node(conv, "disc_1")

        assert node["label"] == "Short msg"

    def test_size_scales_with_turn_count(self):
        low = build_discussion_node(_make_conv(turnCount=1), "d1")
        mid = build_discussion_node(_make_conv(turnCount=10), "d2")
        high = build_discussion_node(_make_conv(turnCount=100), "d3")

        assert low["size"] < mid["size"]
        assert mid["size"] < high["size"]

    def test_size_clamped_to_range(self):
        tiny = build_discussion_node(_make_conv(turnCount=0), "d1")
        huge = build_discussion_node(_make_conv(turnCount=10000), "d2")

        assert tiny["size"] >= 2
        assert huge["size"] <= 8

    def test_handles_missing_fields(self):
        conv = {"sessionId": "s1", "project": "-Users-dev-Foo"}
        node = build_discussion_node(conv, "disc_1")

        assert node["type"] == "discussion"
        assert node["label"] == ""
        assert node["turnCount"] == 0
        assert node["toolsUsed"] == []


class TestBuildDiscussionNodes:
    def test_links_to_correct_domain_hubs(self):
        # Hub keys contain words that appear in the project slug
        domain_hubs = {"myproject": "dom_1", "otherproject": "dom_2"}
        convs = [
            _make_conv(sessionId="s1", project="-Users-dev-MyProject"),
            _make_conv(sessionId="s2", project="-Users-dev-OtherProject"),
        ]

        nodes, edges = build_discussion_nodes(convs, domain_hubs)

        assert len(nodes) == 2
        assert len(edges) == 2
        assert edges[0]["source"] == "dom_1"
        assert edges[0]["type"] == "has-discussion"
        assert edges[1]["source"] == "dom_2"

    def test_fallback_to_first_hub_when_no_match(self):
        # With fallback, unknown domains go to first hub instead of being dropped
        domain_hubs = {"myproject": "dom_1"}
        convs = [
            _make_conv(sessionId="s1", project="-Users-dev-MyProject"),
            _make_conv(sessionId="s2", project="-Users-dev-CompletelyUnrelated"),
        ]

        nodes, edges = build_discussion_nodes(convs, domain_hubs)

        # Both should be included — second falls back to first hub
        assert len(nodes) == 2

    def test_empty_conversations(self):
        nodes, edges = build_discussion_nodes([], {"myproject": "dom_1"})

        assert nodes == []
        assert edges == []

    def test_empty_domain_hubs(self):
        convs = [_make_conv()]
        nodes, edges = build_discussion_nodes(convs, {})

        assert nodes == []
        assert edges == []

    def test_word_matching_finds_hub(self):
        domain_hubs = {"ai architect": "dom_1"}
        convs = [_make_conv(project="-Users-dev-ai-architect-feedback-loop")]

        nodes, edges = build_discussion_nodes(convs, domain_hubs)

        assert len(nodes) == 1
        assert edges[0]["source"] == "dom_1"
