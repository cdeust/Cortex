"""Tests for mcp_server.infrastructure.scanner — ported from scanner.test.js."""

import json

from mcp_server.infrastructure.scanner import (
    read_head_tail,
    group_by_project,
    discover_all_memories,
    discover_conversations,
)


class TestReadHeadTail:
    def test_reads_records_from_small_jsonl(self, tmp_path):
        p = tmp_path / "test.jsonl"
        lines = [
            json.dumps({"type": "user", "message": "hello"}),
            json.dumps({"type": "assistant", "message": "hi"}),
            json.dumps({"type": "user", "message": "bye"}),
        ]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

        records = read_head_tail(p)
        assert isinstance(records, list)
        assert len(records) == 3
        assert records[0]["type"] == "user"
        assert records[1]["type"] == "assistant"

    def test_returns_empty_for_missing(self, tmp_path):
        records = read_head_tail(tmp_path / "nope.jsonl")
        assert isinstance(records, list)
        assert len(records) == 0

    def test_skips_invalid_json_lines(self, tmp_path):
        p = tmp_path / "mixed.jsonl"
        content = (
            "\n".join(
                [
                    json.dumps({"valid": True}),
                    "not valid json {{{",
                    json.dumps({"also": "valid"}),
                ]
            )
            + "\n"
        )
        p.write_text(content, encoding="utf-8")

        records = read_head_tail(p)
        assert len(records) == 2


class TestGroupByProject:
    def test_groups_by_project(self):
        conversations = [
            {"sessionId": "a", "project": "proj-1"},
            {"sessionId": "b", "project": "proj-2"},
            {"sessionId": "c", "project": "proj-1"},
        ]
        groups = group_by_project(conversations)
        assert "proj-1" in groups
        assert "proj-2" in groups
        assert len(groups["proj-1"]) == 2
        assert len(groups["proj-2"]) == 1

    def test_empty_input(self):
        assert group_by_project([]) == {}


class TestDiscoverAllMemories:
    def test_returns_array(self):
        memories = discover_all_memories()
        assert isinstance(memories, list)


class TestDiscoverConversations:
    def test_returns_array(self):
        conversations = discover_conversations()
        assert isinstance(conversations, list)
