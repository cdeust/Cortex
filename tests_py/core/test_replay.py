"""Tests for mcp_server.core.replay — hippocampal replay formatting."""

from mcp_server.core.replay import (
    should_micro_checkpoint,
    format_restoration,
)


class TestShouldMicroCheckpoint:
    def test_error_triggers(self):
        ok, reason = should_micro_checkpoint(
            "RuntimeError: connection failed", [], tool_call_count=10
        )
        assert ok is True
        assert reason == "error_detected"

    def test_decision_triggers(self):
        ok, reason = should_micro_checkpoint(
            "We decided to use PostgreSQL", [], tool_call_count=10
        )
        assert ok is True
        assert reason == "decision_made"

    def test_high_surprise_triggers(self):
        ok, reason = should_micro_checkpoint(
            "Something happened", [], surprise=0.9, tool_call_count=10
        )
        assert ok is True
        assert reason == "high_surprise_event"

    def test_critical_tag_triggers(self):
        ok, reason = should_micro_checkpoint(
            "Content", ["critical", "note"], tool_call_count=10
        )
        assert ok is True
        assert reason == "critical_tag"

    def test_cooldown_prevents_trigger(self):
        ok, reason = should_micro_checkpoint(
            "RuntimeError: something", [], tool_call_count=2, cooldown=5
        )
        assert ok is False

    def test_normal_content_no_trigger(self):
        ok, reason = should_micro_checkpoint(
            "The weather is nice today", ["general"], tool_call_count=10
        )
        assert ok is False

    def test_empty_content(self):
        ok, _ = should_micro_checkpoint("", [], tool_call_count=10)
        assert ok is False


class TestFormatRestoration:
    def test_with_checkpoint(self):
        cp = {
            "current_task": "Writing tests",
            "files_being_edited": '["test.py", "handler.py"]',
            "key_decisions": '["Use SQLite"]',
            "open_questions": '["How to handle concurrency?"]',
            "next_steps": '["Run tests"]',
            "active_errors": '["ImportError in module X"]',
            "custom_context": "Extra context here",
        }
        result = format_restoration(cp, [], [], [])
        assert "Writing tests" in result
        assert "test.py" in result
        assert "Use SQLite" in result
        assert "concurrency" in result
        assert "Run tests" in result
        assert "ImportError" in result
        assert "Extra context" in result

    def test_with_memories(self):
        anchored = [{"content": "Critical fact: always use UTC"}]
        recent = [{"content": "Just stored this", "created_at": "2024-01-01T10:00:00Z"}]
        hot = [{"content": "Hot project memory", "heat": 0.9}]
        result = format_restoration(None, anchored, recent, hot, "/project")
        assert "Critical fact" in result
        assert "Just stored" in result
        assert "Hot project" in result
        assert "/project" in result

    def test_empty_restoration(self):
        result = format_restoration(None, [], [], [])
        assert "Hippocampal Replay" in result

    def test_truncates_long_content(self):
        long_mem = [{"content": "x" * 500, "heat": 0.8}]
        result = format_restoration(None, [], [], long_mem)
        assert "..." in result

    def test_checkpoint_with_list_fields(self):
        cp = {
            "current_task": "Task",
            "files_being_edited": ["a.py", "b.py"],  # Already a list
            "key_decisions": [],
            "open_questions": [],
            "next_steps": [],
            "active_errors": [],
        }
        result = format_restoration(cp, [], [], [])
        assert "a.py" in result
