"""Tests for mcp_server.core.session_extractor — pure logic extraction."""

import pytest

from mcp_server.core.session_extractor import (
    extract_user_messages,
    classify_message,
    score_importance,
    extract_memorable_items,
    extract_session_summary,
    _extract_text,
)


# ── _extract_text ─────────────────────────────────────────────────────────


class TestExtractText:
    def test_string_content(self):
        assert _extract_text("hello world") == "hello world"

    def test_list_content(self):
        content = [
            {"type": "text", "text": "first part"},
            {"type": "text", "text": "second part"},
        ]
        assert _extract_text(content) == "first part second part"

    def test_list_with_non_text_blocks(self):
        content = [
            {"type": "text", "text": "visible"},
            {"type": "tool_use", "name": "Read"},
        ]
        assert _extract_text(content) == "visible"

    def test_none_content(self):
        assert _extract_text(None) == ""

    def test_integer_content(self):
        assert _extract_text(42) == ""

    def test_strips_whitespace(self):
        assert _extract_text("  hello  ") == "hello"


# ── extract_user_messages ─────────────────────────────────────────────────


class TestExtractUserMessages:
    def test_extracts_user_messages(self):
        records = [
            {
                "type": "user",
                "message": {
                    "content": "Decided to use factory pattern for the handler layer."
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "sessionId": "abc",
            },
        ]
        result = extract_user_messages(records)
        assert len(result) == 1
        assert "factory pattern" in result[0]["text"]

    def test_skips_assistant_messages(self):
        records = [
            {"type": "assistant", "message": {"content": "Sure, here's the code..."}},
        ]
        assert extract_user_messages(records) == []

    def test_skips_tool_results(self):
        records = [
            {
                "type": "user",
                "toolUseResult": {"success": True},
                "message": {
                    "content": "tool result data here, needs to be long enough"
                },
            },
        ]
        assert extract_user_messages(records) == []

    def test_skips_meta_messages(self):
        records = [
            {
                "type": "user",
                "isMeta": True,
                "message": {
                    "content": "meta information that should be long enough to pass"
                },
            },
        ]
        assert extract_user_messages(records) == []

    def test_skips_short_messages(self):
        records = [
            {"type": "user", "message": {"content": "yes"}},
        ]
        assert extract_user_messages(records) == []

    def test_skips_interrupted_requests(self):
        records = [
            {
                "type": "user",
                "message": {
                    "content": "[Request interrupted by user] some very long content here"
                },
            },
        ]
        assert extract_user_messages(records) == []

    def test_truncates_long_messages(self):
        long_text = "x" * 3000
        records = [
            {
                "type": "user",
                "message": {"content": long_text},
                "timestamp": "t1",
                "sessionId": "s1",
            },
        ]
        result = extract_user_messages(records)
        assert len(result[0]["text"]) == 2000


# ── classify_message ──────────────────────────────────────────────────────


class TestClassifyMessage:
    def test_decision_detection(self):
        cats = classify_message("We decided to use PostgreSQL instead of MySQL")
        assert "decision" in cats

    def test_error_detection(self):
        cats = classify_message("Got a traceback when running the test suite")
        assert "error" in cats

    def test_architecture_detection(self):
        cats = classify_message(
            "The clean architecture layers should never cross boundaries"
        )
        assert "architecture" in cats

    def test_insight_detection(self):
        cats = classify_message(
            "Turns out the root cause was a race condition in the pool"
        )
        assert "insight" in cats

    def test_multiple_categories(self):
        cats = classify_message("Decided to refactor the architecture after the crash")
        assert "decision" in cats
        assert "architecture" in cats

    def test_no_categories(self):
        cats = classify_message("Hello, how are you doing today?")
        assert cats == []


# ── score_importance ──────────────────────────────────────────────────────


class TestScoreImportance:
    def test_baseline_no_categories(self):
        score = score_importance("some generic text", [])
        assert score == pytest.approx(0.3, abs=0.01)

    def test_decision_boost(self):
        score = score_importance("text", ["decision"])
        assert score > 0.5

    def test_insight_highest(self):
        score = score_importance("text", ["insight"])
        assert score >= 0.6

    def test_long_text_boost(self):
        long = "x" * 250
        short = "x" * 50
        assert score_importance(long, []) > score_importance(short, [])

    def test_prescriptive_boost(self):
        score = score_importance("You must always validate inputs", [])
        assert score > 0.3

    def test_capped_at_1(self):
        score = score_importance(
            "x" * 300 + " always must ```code``` ",
            ["decision", "architecture", "error", "insight"],
        )
        assert score <= 1.0


# ── extract_memorable_items ───────────────────────────────────────────────


class TestExtractMemorableItems:
    def _make_record(self, text, ts="2026-01-01T00:00:00Z", sid="test-session"):
        return {
            "type": "user",
            "message": {"content": text},
            "timestamp": ts,
            "sessionId": sid,
        }

    def test_extracts_important_items(self):
        records = [
            self._make_record(
                "We decided to use the factory pattern for all handler composition roots"
            ),
            self._make_record(
                "The root cause of the crash was a missing null check in the parser module"
            ),
        ]
        items = extract_memorable_items(records, min_importance=0.3)
        assert len(items) >= 1
        assert all("imported" in item["tags"] for item in items)

    def test_filters_low_importance(self):
        records = [
            self._make_record(
                "Hello, can you help me with something? I need some assistance."
            ),
        ]
        items = extract_memorable_items(records, min_importance=0.8)
        assert len(items) == 0

    def test_deduplicates_within_session(self):
        records = [
            self._make_record(
                "Decided to use factory pattern for all the handler implementations"
            ),
            self._make_record(
                "Decided to use factory pattern for all the handler implementations"
            ),
        ]
        items = extract_memorable_items(records, min_importance=0.3)
        assert len(items) == 1

    def test_tags_include_categories(self):
        records = [
            self._make_record(
                "We decided to refactor the architecture to use clean layers"
            ),
        ]
        items = extract_memorable_items(records, min_importance=0.3)
        assert len(items) >= 1
        tags = items[0]["tags"]
        assert "imported" in tags
        assert any(t in tags for t in ["decision", "architecture"])


# ── extract_session_summary ───────────────────────────────────────────────


class TestExtractSessionSummary:
    def test_basic_summary(self):
        records = [
            {
                "type": "user",
                "message": {
                    "content": "Build the import_sessions MCP tool for JARVIS memory system"
                },
                "timestamp": "2026-01-01T10:00:00Z",
                "sessionId": "s123",
                "cwd": "/Users/dev/Developments/jarvis",
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "I'll build that."},
                        {"type": "tool_use", "name": "Read", "input": {}},
                    ]
                },
                "timestamp": "2026-01-01T10:01:00Z",
                "sessionId": "s123",
            },
        ]
        summary = extract_session_summary(records)
        assert summary["session_id"] == "s123"
        assert "jarvis" in summary["cwd"]
        assert "import_sessions" in summary["first_message"]
        assert "Read" in summary["tools_used"]

    def test_empty_records(self):
        summary = extract_session_summary([])
        assert summary["session_id"] == ""
        assert summary["user_count"] == 0

    def test_skips_tool_results_for_first_message(self):
        records = [
            {
                "type": "user",
                "toolUseResult": {"success": True},
                "message": {"content": "tool result"},
                "sessionId": "s1",
            },
            {
                "type": "user",
                "message": {
                    "content": "This is the real first message from the user in the conversation"
                },
                "timestamp": "2026-01-01T00:00:00Z",
                "sessionId": "s1",
            },
        ]
        summary = extract_session_summary(records)
        assert "real first message" in summary["first_message"]
