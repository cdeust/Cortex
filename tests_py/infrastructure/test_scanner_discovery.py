"""Scanner discovery walks: skip rules, error reporting and the scoped cap.

``list_dir`` returns ``iterdir()`` order, which the filesystem decides; the
``ordered`` fixture sorts it so a skipped entry is guaranteed to come before
a kept one, which is what tells "skip" apart from "stop".

source: issue #710 (mutation gate on PR #864)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.infrastructure import file_io, scanner


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(scanner, "CLAUDE_PROJECTS_DIR", root)

    def ordered(path, **kwargs):
        entries = file_io.list_dir(path, **kwargs)
        return None if entries is None else sorted(entries, key=str)

    monkeypatch.setattr(scanner, "list_dir", ordered)
    return root


def _session(project: Path, name: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "user",
        "cwd": str(project),
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"content": "fix the bug please"},
    }
    (project / name).write_text(json.dumps(record) + "\n", encoding="utf-8")


def _memory(project: Path, *names: str) -> Path:
    memory = project / "memory"
    memory.mkdir(parents=True)
    for name in names:
        (memory / name).write_text(f"note {name}\n", encoding="utf-8")
    return memory


class TestDiscoverAllMemories:
    def test_skips_stray_files_empty_projects_index_and_non_markdown(self, projects):
        (projects / "0-stray.txt").write_text("")
        (projects / "a-empty").mkdir()
        _memory(projects / "b-proj", "MEMORY.md", "a.md", "notes.txt", "z.md")

        found = scanner.discover_all_memories()

        assert sorted((m["project"], m["file"]) for m in found) == [
            ("b-proj", "a.md"),
            ("b-proj", "z.md"),
        ]

    def test_an_unreadable_memory_is_reported_with_its_path(
        self, projects, monkeypatch, capsys
    ):
        memory = _memory(projects / "a-proj", "a.md")

        def broken(*args):
            raise ValueError("bad frontmatter")

        monkeypatch.setattr(scanner, "_parse_memory_file", broken)

        assert scanner.discover_all_memories() == []
        assert f"Failed to read {memory / 'a.md'}: bad frontmatter" in (
            capsys.readouterr().err
        )


class TestDiscoverConversations:
    def test_missing_root_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(scanner, "CLAUDE_PROJECTS_DIR", tmp_path / "none")
        assert scanner.discover_conversations() == []

    def test_reads_every_project_and_skips_stray_files(self, projects):
        (projects / "0-stray.txt").write_text("")
        _session(projects / "b-proj", "s1.jsonl")
        _session(projects / "c-proj", "s2.jsonl")

        found = scanner.discover_conversations()

        assert isinstance(found, list)
        assert sorted(c["project"] for c in found) == ["b-proj", "c-proj"]


class TestDiscoverConversationsForProjects:
    def test_a_limit_of_one_returns_one_record(self, projects):
        _session(projects / "a-proj", "s1.jsonl")
        _session(projects / "a-proj", "s2.jsonl")

        found = scanner.discover_conversations_for_projects(["a-proj"], limit=1)

        assert len(found) == 1

    def test_a_missing_project_does_not_stop_the_scan(self, projects):
        _session(projects / "b-proj", "s1.jsonl")

        found = scanner.discover_conversations_for_projects(
            ["a-missing", "b-proj"], limit=20
        )

        assert [c["project"] for c in found] == ["b-proj"]
