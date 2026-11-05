"""``backfill_helpers.discover_files``: skip rules, newest-first order, cap.

The cap is ``max_files * 3`` accepted files (over-fetch, filtered later by
the caller), taken in sorted project order and reverse-sorted file order.

source: issue #710 (mutation gate on PR #864)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.handlers import backfill_helpers


@pytest.fixture
def projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(backfill_helpers, "CLAUDE_PROJECTS_DIR", root)
    return root


def _sessions(project: Path, *names: str) -> None:
    project.mkdir(parents=True, exist_ok=True)
    for name in names:
        (project / name).write_text("{}\n")


def test_missing_root_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(backfill_helpers, "CLAUDE_PROJECTS_DIR", tmp_path / "none")
    assert backfill_helpers.discover_files("", max_files=10) == []


def test_a_stray_file_before_the_projects_is_skipped(projects):
    (projects / "0-stray.txt").write_text("")
    _sessions(projects / "a-proj", "s1.jsonl")

    found = backfill_helpers.discover_files("", max_files=10)

    assert [(p.name, slug) for p, slug in found] == [("s1.jsonl", "a-proj")]


def test_filter_skips_earlier_projects_and_keeps_later_ones(projects):
    _sessions(projects / "a-other", "s1.jsonl")
    _sessions(projects / "b-keep", "s2.jsonl")

    found = backfill_helpers.discover_files("keep", max_files=10)

    assert [(p.name, slug) for p, slug in found] == [("s2.jsonl", "b-keep")]


def test_files_come_newest_name_first(projects):
    _sessions(projects / "a-proj", "s1.jsonl", "s2.jsonl", "s3.jsonl")

    found = backfill_helpers.discover_files("", max_files=10)

    assert [p.name for p, _ in found] == ["s3.jsonl", "s2.jsonl", "s1.jsonl"]


def test_cap_is_three_times_max_files_across_projects(projects):
    _sessions(projects / "a-proj", *(f"s{i}.jsonl" for i in range(5)))
    _sessions(projects / "b-proj", "t1.jsonl")

    found = backfill_helpers.discover_files("", max_files=1)

    assert [(p.name, slug) for p, slug in found] == [
        ("s4.jsonl", "a-proj"),
        ("s3.jsonl", "a-proj"),
        ("s2.jsonl", "a-proj"),
    ]


def test_cap_reached_at_a_project_boundary_stops_the_scan(projects):
    _sessions(projects / "a-proj", "s1.jsonl", "s2.jsonl", "s3.jsonl")
    _sessions(projects / "b-proj", "t1.jsonl")

    found = backfill_helpers.discover_files("", max_files=1)

    assert [slug for _, slug in found] == ["a-proj"] * 3
