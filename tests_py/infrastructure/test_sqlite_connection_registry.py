"""Lifecycle and optional-extension contract for thread-local SQLite handles."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_connection_registry import (
    SqliteConnectionRegistry,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

# source: repository worker teardown convention in
# tests_py/infrastructure/test_workflow_graph_source_ast.py.
_THREAD_SAFETY_BOUND_SECONDS = 5


def _join(thread: threading.Thread) -> None:
    thread.join(timeout=_THREAD_SAFETY_BOUND_SECONDS)
    assert not thread.is_alive()


def test_registry_owns_and_closes_every_thread_connection(tmp_path: Path) -> None:
    registry = SqliteConnectionRegistry(str(tmp_path / "registry.sqlite3"))
    main_connection = registry.connection()
    worker_connections: list[sqlite3.Connection] = []
    post_close_errors: list[Exception] = []
    worker_ready = threading.Event()
    close_finished = threading.Event()

    def worker_lifecycle() -> None:
        worker_connections.append(registry.connection())
        worker_ready.set()
        assert close_finished.wait(timeout=_THREAD_SAFETY_BOUND_SECONDS)
        try:
            registry.connection()
        except Exception as exc:  # pragma: no cover - diagnostic boundary
            post_close_errors.append(exc)

    worker = threading.Thread(target=worker_lifecycle)

    worker.start()
    assert worker_ready.wait(timeout=_THREAD_SAFETY_BOUND_SECONDS)
    assert len(worker_connections) == 1
    assert worker_connections[0] is not main_connection

    registry.close()
    close_finished.set()
    _join(worker)
    for connection in (main_connection, worker_connections[0]):
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    assert len(post_close_errors) == 1
    assert isinstance(post_close_errors[0], sqlite3.ProgrammingError)
    assert "registry is closed" in str(post_close_errors[0])
    with pytest.raises(sqlite3.ProgrammingError, match="registry is closed"):
        registry.connection()


def test_future_worker_loads_enabled_vector_extension() -> None:
    pytest.importorskip("sqlite_vec")
    store = SqliteMemoryStore()
    if not store.has_vec:
        pytest.skip("sqlite-vec cannot be loaded on this SQLite build")
    observed: list[tuple[int, int]] = []
    errors: list[Exception] = []

    def insert_vector() -> None:
        try:
            embedding = np.zeros(384, dtype=np.float32).tobytes()
            memory_id = store.insert_memory(
                {"content": "worker-vector", "embedding": embedding}
            )
            count = store._raw_conn.execute(
                "SELECT COUNT(*) FROM memories_vec WHERE rowid = ?", (memory_id,)
            ).fetchone()[0]
            observed.append((memory_id, count))
        except Exception as exc:  # pragma: no cover - diagnostic boundary
            errors.append(exc)

    worker = threading.Thread(target=insert_vector)
    worker.start()
    _join(worker)

    assert errors == []
    assert len(observed) == 1
    assert observed[0][1] == 1
    store.close()


def test_journal_mode_matches_storage_kind(tmp_path: Path) -> None:
    file_registry = SqliteConnectionRegistry(str(tmp_path / "journal.sqlite3"))
    memory_registry = SqliteConnectionRegistry(":memory:")

    file_mode = file_registry.connection().execute("PRAGMA journal_mode").fetchone()[0]
    memory_mode = (
        memory_registry.connection().execute("PRAGMA journal_mode").fetchone()[0]
    )
    assert file_mode == "wal"
    assert memory_mode == "memory"
    file_registry.close()
    memory_registry.close()


def test_relative_database_path_is_stable_after_cwd_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    relative_path = Path("relative.sqlite3")
    store = SqliteMemoryStore(str(relative_path))
    moved_cwd = tmp_path / "moved-cwd"
    moved_cwd.mkdir()
    monkeypatch.chdir(moved_cwd)
    observed_ids: list[int] = []
    errors: list[Exception] = []

    def insert_from_worker() -> None:
        try:
            observed_ids.append(
                store.insert_entity({"name": "stable-path", "type": "test"})
            )
        except Exception as exc:  # pragma: no cover - diagnostic boundary
            errors.append(exc)

    worker = threading.Thread(target=insert_from_worker)
    worker.start()
    _join(worker)
    store.close()

    assert errors == []
    assert len(observed_ids) == 1
    assert (tmp_path / relative_path).is_file()
    assert not (moved_cwd / relative_path).exists()
