"""scripts/setup_db.py ``_count_session_files`` reads the host's transcript root.

SessionStart takes ``session_files`` from this script on its PostgreSQL setup
fallback path (``session_start.py``); the setup scripts print it too. A count
pinned to ``~/.claude/projects`` never saw transcripts under a relocated
``CLAUDE_CONFIG_DIR``.

source: issue #710; PR #864 review
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_counts_jsonl_under_the_configured_transcript_root(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    import setup_db
    from mcp_server.infrastructure import config

    projects = tmp_path / "host" / "projects"
    monkeypatch.setattr(config, "CLAUDE_PROJECTS_DIR", projects)
    assert setup_db._count_session_files() == 0

    (projects / "p1").mkdir(parents=True)
    (projects / "p1" / "a.jsonl").write_text("{}")
    (projects / "p1" / "b.jsonl").write_text("{}")
    (projects / "p1" / "notes.txt").write_text("")
    (projects / "p2").mkdir()
    (projects / "p2" / "c.jsonl").write_text("{}")
    assert setup_db._count_session_files() == 3
