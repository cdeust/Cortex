"""Codex rollouts become conversation records for the profile rebuild (#726).

Rollout shapes follow openai/codex@e7f32cf: `session_meta` first,
`event_msg` `user_message` (legacy) or `item_completed` with a `UserMessage`
item (paginated) for typed prompts, `response_item` for assistant turns and
tool calls. The committed ADR-1081 excerpt carries redacted `item_completed`
payloads, so it is read here for its counts only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.infrastructure.codex_history import (
    codex_sessions_dir,
    discover_codex_conversations,
    parse_rollout_conversation,
)
from mcp_server.infrastructure.scanner_parse import (
    extract_message_stats,
    extract_metadata_fields,
)

_EXCERPT = Path(__file__).parent / "fixtures" / "codex_rollout_excerpt.jsonl"


def _meta(cwd: str | None, thread_source: str | None = "user") -> dict:
    payload: dict = {"id": "t1", "timestamp": "2026-09-01T00:00:00Z"}
    if cwd is not None:
        payload["cwd"] = cwd
    if thread_source is not None:
        payload["thread_source"] = thread_source
    return {
        "timestamp": "2026-09-01T00:00:00Z",
        "type": "session_meta",
        "payload": payload,
    }


def _legacy_prompt(text: str, ts: str) -> dict:
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {"type": "user_message", "message": text},
    }


def _paginated_prompt(text: str, ts: str) -> dict:
    content = [{"type": "text", "text": text}]
    item = {"type": "UserMessage", "id": "u", "content": content}
    return {
        "timestamp": ts,
        "type": "event_msg",
        "payload": {"type": "item_completed", "turn_id": "1", "item": item},
    }


def _assistant(ts: str) -> dict:
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {"type": "message", "role": "assistant", "content": []},
    }


def _tool(name: str, ts: str) -> dict:
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {"type": "function_call", "name": name, "arguments": "{}"},
    }


def _injected_context(ts: str) -> dict:
    text = "<environment_context> x </environment_context>"
    block = {"type": "input_text", "text": text}
    return {
        "timestamp": ts,
        "type": "response_item",
        "payload": {"type": "message", "role": "user", "content": [block]},
    }


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _session(cwd: str = "/work/repo", prompt=_legacy_prompt) -> list[dict]:
    return [
        _meta(cwd),
        _injected_context("2026-09-01T00:00:01Z"),
        prompt("fix the failing test", "2026-09-01T00:00:02Z"),
        _tool("exec", "2026-09-01T00:00:03Z"),
        _tool("apply_patch", "2026-09-01T00:00:04Z"),
        _assistant("2026-09-01T00:00:05Z"),
        prompt("now push it", "2026-09-01T00:01:00Z"),
        _assistant("2026-09-01T00:02:00Z"),
    ]


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    return tmp_path / "codex"


def _rollout(home: Path, name: str, records: list[dict]) -> Path:
    return _write(home / "sessions" / "2026" / "09" / "01" / name, records)


class TestCodexSessionsDir:
    def test_codex_home_names_the_root(self, codex_home):
        assert codex_sessions_dir() == codex_home / "sessions"

    def test_unset_or_empty_codex_home_is_dot_codex(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("CODEX_HOME", "")
        assert codex_sessions_dir() == Path.home() / ".codex" / "sessions"
        monkeypatch.delenv("CODEX_HOME")
        assert codex_sessions_dir() == Path.home() / ".codex" / "sessions"


class TestParseRolloutConversation:
    @pytest.mark.parametrize("prompt", [_legacy_prompt, _paginated_prompt])
    def test_counts_prompts_turns_and_tools(self, tmp_path, prompt):
        path = _write(tmp_path / "rollout-a.jsonl", _session(prompt=prompt))
        record = parse_rollout_conversation(path)
        assert record is not None
        assert record["project"] == "-work-repo"
        assert record["cwd"] == "/work/repo"
        assert record["source"] == "codex"
        assert (record["userCount"], record["assistantCount"]) == (2, 2)
        assert record["turnCount"] == 2
        assert record["toolsUsed"] == ["exec", "apply_patch"]
        assert record["firstMessage"] == "fix the failing test"
        assert record["allText"] == "fix the failing test now push it"
        assert record["startedAt"] == "2026-09-01T00:00:00Z"
        assert record["endedAt"] == "2026-09-01T00:02:00Z"
        assert record["duration"] == 120000

    def test_injected_context_is_not_a_prompt(self, tmp_path):
        path = _write(tmp_path / "rollout-a.jsonl", _session())
        record = parse_rollout_conversation(path)
        assert "environment_context" not in (record["allText"] or "")

    def test_claude_reader_sees_nothing_in_the_same_file(self, tmp_path):
        """The defect #726 reports, pinned so this module's reason stays visible."""
        records = _session()
        stats = extract_message_stats(records)
        assert (stats["user_count"], stats["assistant_count"]) == (0, 0)
        assert extract_metadata_fields(records)["cwd"] is None

    def test_committed_excerpt_counts(self):
        record = parse_rollout_conversation(_EXCERPT)
        assert record is not None
        assert record["project"] == "-Users-example-project"
        assert record["assistantCount"] == 2
        assert record["userCount"] == 0

    @pytest.mark.parametrize(
        "source", ["subagent", "guardian_review", "memory_consolidation"]
    )
    def test_non_user_threads_are_skipped(self, tmp_path, source):
        records = _session()
        records[0] = _meta("/work/repo", thread_source=source)
        assert parse_rollout_conversation(_write(tmp_path / "r.jsonl", records)) is None

    def test_rollout_without_thread_source_is_a_user_thread(self, tmp_path):
        records = _session()
        records[0] = _meta("/work/repo", thread_source=None)
        assert parse_rollout_conversation(_write(tmp_path / "r.jsonl", records))

    def test_no_session_meta_no_cwd_or_no_message_is_none(self, tmp_path):
        no_meta = _write(tmp_path / "a.jsonl", _session()[1:])
        no_cwd = _write(tmp_path / "b.jsonl", [_meta(None)] + _session()[1:])
        empty = _write(tmp_path / "c.jsonl", [_meta("/work/repo")])
        assert parse_rollout_conversation(no_meta) is None
        assert parse_rollout_conversation(no_cwd) is None
        assert parse_rollout_conversation(empty) is None


class TestDiscoverCodexConversations:
    def test_missing_sessions_dir_is_empty(self, codex_home):
        assert discover_codex_conversations() == []

    def test_reads_every_rollout_once_in_path_order(self, codex_home):
        _rollout(codex_home, "rollout-2026-09-01T00-00-00-a.jsonl", _session("/work/a"))
        _rollout(codex_home, "rollout-2026-09-01T01-00-00-b.jsonl", _session("/work/b"))
        _write(codex_home / "sessions" / "notes.jsonl", _session("/work/c"))
        first = discover_codex_conversations()
        assert [r["project"] for r in first] == ["-work-a", "-work-b"]
        assert discover_codex_conversations() == first
