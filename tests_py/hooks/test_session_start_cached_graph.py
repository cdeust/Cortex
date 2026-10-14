"""SessionStart reads the code-graph memo through the configured store.

Issue #751: ``_lookup_cached_graph_path`` read the memo through psycopg
only, so on the SQLite backend (the plugin default) it always returned
None, ``graph_is_stale(None)`` was True, and every SessionStart with a
discoverable pipeline spawned a detached ingest. These tests run the real
SQLite store, the real memo writer and the real TTL gate; only the pipeline
discovery, the launcher and ``Popen`` are stubbed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcp_server.handlers.ingest_helpers import memoise_graph_path
from mcp_server.hooks import session_start, session_start_background as background
from mcp_server.infrastructure import memory_store, pipeline_discovery
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_TWO_DAYS = 2 * 24 * 3600  # older than the default 24 h TTL (ADR-0585)


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A project, a SQLite store served as the shared store, a discoverable
    pipeline and a launcher stub. Yields ``(project_root, store, spawned)``."""
    store = SqliteMemoryStore(str(tmp_path / "memory.db"))
    monkeypatch.setattr(memory_store, "get_shared_store", lambda *a, **k: store)
    monkeypatch.setattr(
        pipeline_discovery, "discover_pipeline_command", lambda root: ["ap"]
    )
    monkeypatch.delenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", raising=False)
    plugin_root = tmp_path / "plugin"
    (plugin_root / "scripts").mkdir(parents=True)
    (plugin_root / "scripts" / "launcher.py").write_text("# stub\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.delenv("CORTEX_CLAUDE_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    spawned = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(background.subprocess, "Popen", spawned)
    root = tmp_path / "app"
    root.mkdir()
    yield str(root), store, spawned
    store.close()


def _reanalyze(root: str) -> None:
    """The reanalysis SessionStart runs: the real store-backed memo lookup."""
    background._maybe_background_reanalyze(
        root, session_start._lookup_cached_graph_path
    )


def _memoised_graph(tmp_path: Path, store, root: str, age_seconds: float) -> Path:
    graph = tmp_path / "graphs" / "graph.ladybug"
    graph.parent.mkdir(parents=True, exist_ok=True)
    graph.write_bytes(b"graph")
    built = time.time() - age_seconds
    os.utime(graph, (built, built))
    assert memoise_graph_path(store, root, str(graph)) is not None
    return graph


def test_lookup_reads_the_memo_from_the_sqlite_store(project, tmp_path):
    root, store, _spawned = project
    graph = _memoised_graph(tmp_path, store, root, age_seconds=0)
    assert session_start._lookup_cached_graph_path(root) == str(graph)


def test_a_memo_flagged_stale_is_not_served(project, tmp_path):
    """A stale memo is skipped by the store's tag query, on SQLite as on
    PostgreSQL (the ``is_stale`` filter ADR-1104's SQLite twin applied)."""
    root, store, _spawned = project
    _memoised_graph(tmp_path, store, root, age_seconds=0)
    rows = store.get_all_memories_for_decay()
    assert rows, "the memo was written"
    for row in rows:
        store.mark_memory_stale(row["id"])
    assert session_start._lookup_cached_graph_path(root) is None


def test_a_fresh_graph_spawns_no_ingest(project, tmp_path):
    root, store, spawned = project
    _memoised_graph(tmp_path, store, root, age_seconds=0)
    _reanalyze(root)
    spawned.assert_not_called()


def test_a_graph_older_than_the_ttl_spawns_one_ingest(project, tmp_path):
    root, store, spawned = project
    _memoised_graph(tmp_path, store, root, age_seconds=_TWO_DAYS)
    _reanalyze(root)
    spawned.assert_called_once()


def test_no_memo_spawns_the_first_ingest(project):
    root, _store, spawned = project
    _reanalyze(root)
    spawned.assert_called_once()


def test_an_unreadable_store_spawns_nothing(project, monkeypatch, capsys):
    root, _store, spawned = project

    def _unreachable(*args, **kwargs):
        raise OSError("store unreachable")

    monkeypatch.setattr(memory_store, "get_shared_store", _unreachable)
    _reanalyze(root)
    spawned.assert_not_called()
    err = capsys.readouterr().err
    assert "background pipeline reanalysis skipped" in err
    assert "store unreachable" in err


def test_a_failed_or_running_ingest_is_not_restarted_within_the_ttl(project):
    """No memo yet (the first ingest failed, or is still running): the next
    SessionStart inside the TTL window starts no second ingest."""
    root, _store, spawned = project
    _reanalyze(root)
    _reanalyze(root)
    spawned.assert_called_once()


def test_the_ttl_window_reopens_the_slot(project, monkeypatch):
    root, _store, spawned = project
    _reanalyze(root)
    monkeypatch.setenv("CORTEX_PIPELINE_GRAPH_TTL_HOURS", "0")
    _reanalyze(root)
    assert spawned.call_count == 2
