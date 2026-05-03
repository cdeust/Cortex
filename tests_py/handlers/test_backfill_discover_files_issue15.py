"""Tests for issue #15 — discover_files walks the four legitimate session layouts.

Pre-fix `glob("*.jsonl")` only saw flat-parent sessions, missing ~89% of
session content when subagent / teammate sessions are active. Post-fix
uses `rglob` with explicit accept rules for the four observed layouts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.handlers import backfill_helpers


@pytest.fixture
def fake_projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fake ~/.claude/projects/ tree with all four layouts.

    Layout taxonomy (from issue #15):
      1. Flat parent           <slug>/<uuid>.jsonl
      2. UUID-dir parent       <slug>/<uuid>/<uuid>.jsonl
      3. Subagent (data dir)   <slug>/<parent>/data/subagents/agent-<id>.jsonl
      4. Subagent (direct)     <slug>/<parent>/agent-<id>.jsonl
    """
    claude_dir = tmp_path / "claude"
    projects_dir = claude_dir / "projects"
    projects_dir.mkdir(parents=True)

    slug = "-Users-test-project"
    project = projects_dir / slug
    project.mkdir()

    # Layout 1: flat parent
    (project / "11111111-aaaa-bbbb-cccc-111111111111.jsonl").write_text("{}\n")

    # Layout 2: UUID-dir parent (file basename matches dir name)
    uuid_dir = project / "22222222-aaaa-bbbb-cccc-222222222222"
    uuid_dir.mkdir()
    (uuid_dir / "22222222-aaaa-bbbb-cccc-222222222222.jsonl").write_text("{}\n")

    # Layout 3: subagent under data/subagents/
    parent3 = project / "33333333-aaaa-bbbb-cccc-333333333333"
    sub3 = parent3 / "data" / "subagents"
    sub3.mkdir(parents=True)
    (sub3 / "agent-ad89583639974911f.jsonl").write_text("{}\n")

    # Layout 4: subagent direct under parent
    parent4 = project / "44444444-aaaa-bbbb-cccc-444444444444"
    parent4.mkdir()
    (parent4 / "agent-be9468a740885022g.jsonl").write_text("{}\n")

    # Decoy: a tool-result-like nested .jsonl that is NOT a session
    # (file basename doesn't match parent name and doesn't start with agent-).
    decoy = parent3 / "data" / "tool-results"
    decoy.mkdir(parents=True)
    (decoy / "random-payload.jsonl").write_text("{}\n")

    monkeypatch.setattr(backfill_helpers, "CLAUDE_DIR", claude_dir)
    return projects_dir


def test_walks_all_four_session_layouts(fake_projects_dir: Path) -> None:
    """All four legitimate session layouts must be discovered."""
    results = backfill_helpers.discover_files(project_filter="", max_files=100)
    found_names = {p.name for p, _ in results}

    # Layout 1: flat parent
    assert "11111111-aaaa-bbbb-cccc-111111111111.jsonl" in found_names
    # Layout 2: UUID-dir parent
    assert "22222222-aaaa-bbbb-cccc-222222222222.jsonl" in found_names
    # Layout 3: subagent in data/subagents/
    assert "agent-ad89583639974911f.jsonl" in found_names
    # Layout 4: subagent direct under parent
    assert "agent-be9468a740885022g.jsonl" in found_names


def test_skips_decoy_nested_jsonl(fake_projects_dir: Path) -> None:
    """Nested .jsonl files that don't match the four layouts (e.g. tool-result
    payloads parked under data/tool-results/) must NOT be picked up."""
    results = backfill_helpers.discover_files(project_filter="", max_files=100)
    found_names = {p.name for p, _ in results}
    assert "random-payload.jsonl" not in found_names


def test_returns_correct_count(fake_projects_dir: Path) -> None:
    """Exactly four sessions in the fake tree; the decoy is filtered out."""
    results = backfill_helpers.discover_files(project_filter="", max_files=100)
    assert len(results) == 4


def test_respects_project_filter(fake_projects_dir: Path) -> None:
    """project_filter still narrows results to matching slugs."""
    results = backfill_helpers.discover_files(project_filter="test-project", max_files=100)
    assert len(results) == 4
    results_no_match = backfill_helpers.discover_files(project_filter="nope", max_files=100)
    assert len(results_no_match) == 0
