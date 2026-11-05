"""``import_sessions._discover_jsonl_files``: which transcripts are imported.

Top-level ``*.jsonl`` files of each project directory, in sorted order; no
stray root files, no directories, no non-JSONL files, no subagent sessions.

source: issue #710 (mutation gate on PR #864)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.handlers import import_sessions


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(import_sessions, "CLAUDE_PROJECTS_DIR", root)
    return root


def _found(project_filter: str = "") -> list[tuple[str, str]]:
    found = import_sessions._discover_jsonl_files(project_filter)
    return [(path.name, project) for path, project in found]


def test_missing_root_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(import_sessions, "CLAUDE_PROJECTS_DIR", tmp_path / "none")
    assert import_sessions._discover_jsonl_files("") == []


def test_only_top_level_jsonl_session_files_are_imported(projects):
    (projects / "0-stray.txt").write_text("")
    target = projects / "b-target"
    target.mkdir()
    (target / "a-subagent-1.jsonl").write_text("{}\n")
    (target / "b-notes.txt").write_text("")
    (target / "c-dir.jsonl").mkdir()
    (target / "d-session.jsonl").write_text("{}\n")
    (target / "e-session.jsonl").write_text("{}\n")

    assert _found() == [
        ("d-session.jsonl", "b-target"),
        ("e-session.jsonl", "b-target"),
    ]


def test_filter_skips_earlier_projects_and_keeps_the_named_one(projects):
    for name in ("a-other", "b-target", "c-later"):
        (projects / name).mkdir()
        (projects / name / "s.jsonl").write_text("{}\n")

    assert _found("b-target") == [("s.jsonl", "b-target")]


def test_a_helper_agents_directory_is_skipped_whole(projects):
    # The test name avoids the word itself: pytest puts it in tmp_path.
    (projects / "a-subagents").mkdir()
    (projects / "a-subagents" / "s.jsonl").write_text("{}\n")
    (projects / "b-proj").mkdir()
    (projects / "b-proj" / "t.jsonl").write_text("{}\n")

    assert _found() == [("t.jsonl", "b-proj")]
