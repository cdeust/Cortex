"""Tests for mcp_server.infrastructure.scanner — ported from scanner.test.js."""

import json

from mcp_server.infrastructure.scanner import (
    read_head_tail,
    group_by_project,
    discover_all_memories,
    discover_conversations,
    discover_conversations_for_projects,
)


def _write_session(proj_dir, name, n_user=2, n_assistant=2):
    """Write a minimal-but-real JSONL session file into a project dir."""
    proj_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": "user",
                "slug": "s",
                "cwd": str(proj_dir),
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the bug please"},
            }
        )
    ]
    for _ in range(n_assistant):
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:05:00Z",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Read", "input": {}}]
                    },
                }
            )
        )
    (proj_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


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

    def test_parses_legacy_memory_file_with_frontmatter(self, tmp_path, monkeypatch):
        """parse_yaml_frontmatter returns a NamedTuple; pre-fix the scanner
        indexed it with strings ("tuple indices must be integers"), so every
        legacy projects/*/memory/*.md read failed and setup imported zero
        memory files (each failure swallowed to stderr by the caller)."""
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        mem_dir = tmp_path / "projects" / "proj-a" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "auth-decision.md").write_text(
            "---\n"
            "name: auth-decision\n"
            "description: JWT over sessions\n"
            "type: decision\n"
            "---\n"
            "We chose JWT.\n",
            encoding="utf-8",
        )

        memories = discover_all_memories()

        assert len(memories) == 1
        m = memories[0]
        assert m["name"] == "auth-decision"
        assert m["description"] == "JWT over sessions"
        assert m["type"] == "decision"
        assert m["body"] == "We chose JWT."
        assert m["project"] == "proj-a"

    def test_parses_memory_file_without_frontmatter(self, tmp_path, monkeypatch):
        """No-frontmatter files fall back to filename-derived name and the
        full content as body — same NamedTuple contract, empty meta."""
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        mem_dir = tmp_path / "projects" / "proj-b" / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "plain-note.md").write_text("just a plain note\n", encoding="utf-8")

        memories = discover_all_memories()

        assert len(memories) == 1
        assert memories[0]["name"] == "plain-note"
        assert memories[0]["type"] == "unknown"
        assert memories[0]["body"] == "just a plain note"


class TestDiscoverConversations:
    def test_returns_array(self):
        conversations = discover_conversations()
        assert isinstance(conversations, list)


class TestDiscoverConversationsForProjects:
    def test_scopes_to_requested_projects_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        projects_dir = tmp_path / "projects"
        _write_session(projects_dir / "proj-a", "s1.jsonl")
        _write_session(projects_dir / "proj-b", "s1.jsonl")

        result = discover_conversations_for_projects(["proj-a"], limit=20)

        assert len(result) == 1
        assert result[0]["toolsUsed"] == ["Read"]

    def test_never_touches_unrequested_project_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        projects_dir = tmp_path / "projects"
        _write_session(projects_dir / "proj-a", "s1.jsonl")
        # proj-b intentionally has a corrupt/unreadable-shape file; if the
        # scoped scan ever touched it, this would still not raise (parser
        # is defensive), but asserting proj-b's slug never appears proves
        # the directory was skipped entirely.
        (projects_dir / "proj-b").mkdir(parents=True)
        (projects_dir / "proj-b" / "s1.jsonl").write_text("not json\n")

        result = discover_conversations_for_projects(["proj-a"], limit=20)

        assert all(c["project"] == "proj-a" for c in result)

    def test_bounded_by_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        projects_dir = tmp_path / "projects"
        for i in range(5):
            _write_session(projects_dir / "proj-a", f"s{i}.jsonl")

        result = discover_conversations_for_projects(["proj-a"], limit=3)

        assert len(result) == 3

    def test_empty_project_ids_returns_empty_without_io(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        # No projects dir created at all -- if this touched the filesystem
        # looking for it beyond the guard clause, it would still return []
        # (list_dir is defensive), so this mainly documents the contract.
        assert discover_conversations_for_projects([], limit=20) == []

    def test_zero_limit_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        projects_dir = tmp_path / "projects"
        _write_session(projects_dir / "proj-a", "s1.jsonl")

        assert discover_conversations_for_projects(["proj-a"], limit=0) == []

    def test_unknown_project_id_skipped_gracefully(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        (tmp_path / "projects").mkdir()

        assert discover_conversations_for_projects(["does-not-exist"], limit=20) == []
