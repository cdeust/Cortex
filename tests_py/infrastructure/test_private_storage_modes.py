"""Personal data is created owner-only (audit 2026-10-21, E18; ADR-1112).

The audit measured ``memory.db``, telemetry and logs at 0644/0664 inside
0755/0775 directories (no umask or chmod for the store,
``sqlite_store.py:126``, ``artifact_store.py:39``). Each test writes through
a production API under the suite's private ``CORTEX_CLAUDE_DIR``, with the
common umask 022, and checks the mode the file and its directory get.

Only APIs that exist on ``main`` are used, so this file also measures the
pre-fix behaviour.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def umask_022():
    old = os.umask(0o022)
    yield
    os.umask(old)


@pytest.fixture
def methodology(tmp_path, monkeypatch):
    root = tmp_path / "claude"
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(root))
    return root / "methodology"


def test_sqlite_database_wal_and_shm_are_owner_only(umask_022, methodology):
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    store = SqliteMemoryStore(str(methodology / "memory.db"))
    try:
        store.insert_memory({"content": "x", "tags": [], "domain": "d"})
        files = [
            methodology / n for n in ("memory.db", "memory.db-wal", "memory.db-shm")
        ]
        assert {f.name: _mode(f) for f in files if f.exists()} == {
            f.name: 0o600 for f in files if f.exists()
        }
        assert (methodology / "memory.db-wal").exists()
        assert _mode(methodology) == 0o700
    finally:
        store.close()


def test_rotating_logs_and_telemetry_lines_are_owner_only(umask_022, methodology):
    from mcp_server.shared.log_rotation import open_rotating_log

    for name in ("telemetry.jsonl", "consolidate.log"):
        with open_rotating_log(methodology / name) as stream:
            stream.write("{}\n")
        assert _mode(methodology / name) == 0o600, name
    assert _mode(methodology) == 0o700


def test_artifacts_and_wiki_pages_are_owner_only(umask_022, methodology, monkeypatch):
    from mcp_server.infrastructure import artifact_store, wiki_store

    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", methodology / "artifacts")
    artifact = artifact_store.store_artifact("raw tool output\n" * 300)
    assert _mode(artifact) == 0o600
    assert _mode(artifact.parent) == 0o700
    wiki_store.write_page(methodology / "wiki", "notes/a.md", "# a\n")
    assert _mode(methodology / "wiki" / "notes" / "a.md") == 0o600
    assert _mode(methodology / "wiki" / "notes") == 0o700


def test_a_project_file_outside_the_data_roots_keeps_the_umask(
    umask_022, methodology, tmp_path
):
    """CLAUDE.md sections and docs/adr mirrors belong to the user's repository."""
    from mcp_server.infrastructure import wiki_store

    project = tmp_path / "repo"
    wiki_store.write_page(project / "wiki", "notes/b.md", "# b\n")
    assert _mode(project / "wiki" / "notes" / "b.md") == 0o644
