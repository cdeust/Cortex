"""Hosted regressions for PR #827's review findings.

source: hosted unit job 122814815963; native findings 4400573470 and 4400573476.
"""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from mcp_server.handlers import remember
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_exact import collapse_exact, insert_exact
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.handlers.test_issue_707_exact_duplicates import store as store


def test_explicit_correction_preserves_edge_when_text_exists(store, monkeypatch):
    monkeypatch.setattr(remember, "_store", store)
    old = asyncio.run(remember.handler({"content": "Timeout is thirty", "force": True}))
    replacement = {"content": "Timeout is sixty", "force": True}
    existing = asyncio.run(remember.handler(dict(replacement)))
    corrected = asyncio.run(
        remember.handler({**replacement, "supersedes_id": old["memory_id"]})
    )
    assert existing["stored"] and corrected["stored"]
    assert corrected["action"] == "superseded"
    assert (
        store.get_memory(old["memory_id"])["superseded_by_id"] == corrected["memory_id"]
    )


def test_benchmark_cannot_refuse_a_real_write(store):
    benchmark = store.insert_memory(
        {"content": "benchmark identity", "is_benchmark": True}
    )
    real, inserted = insert_exact(store, {"content": "benchmark identity"})
    assert inserted and real != benchmark
    assert insert_exact(store, {"content": "benchmark identity"}) == (real, False)


def test_benchmark_cannot_hide_a_real_memory(store):
    real = store.insert_memory({"content": "benchmark collapse", "heat": 0.0})
    benchmark = store.insert_memory(
        {"content": "benchmark collapse", "heat": 1.0, "is_benchmark": True}
    )
    assert collapse_exact(store) == {"superseded_total": 0}
    assert store.get_memory(real)["superseded_by_id"] is None
    assert store.get_memory(benchmark)["superseded_by_id"] is None


@pytest.mark.parametrize("tags", [None, ["Memory-Replica"]])
def test_replica_exclusion_uses_exact_case_and_accepts_null_tags(store, tags):
    first, inserted = insert_exact(store, {"content": "replica tag case", "tags": tags})
    second, inserted_again = insert_exact(
        store, {"content": "replica tag case", "tags": tags}
    )
    assert inserted and not inserted_again and second == first


def test_same_text_in_superseded_rows_can_be_written_again(store):
    first, _ = insert_exact(store, {"content": "restored exact content"})
    head, _ = store.supersede_atomic({"content": "different head"}, first)
    assert head is not None
    replay, inserted = insert_exact(store, {"content": "restored exact content"})
    assert inserted and replay != first


@pytest.mark.parametrize("pool_disabled", [False, True])
def test_writer_holds_database_lock_before_insert(store, monkeypatch, pool_disabled):
    monkeypatch.setattr(get_memory_settings(), "POOL_DISABLED", pool_disabled)
    entered, release = Event(), Event()
    data = {"content": "lock held before insertion"}
    name = (
        "_insert_memory_rows"
        if isinstance(store, SqliteMemoryStore)
        else "_insert_memory_on"
    )
    original = getattr(store, name)

    def paused(*args):
        entered.set()
        release.wait()
        return original(*args)

    monkeypatch.setattr(store, name, paused)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(insert_exact, store, data)
        future.add_done_callback(lambda _: entered.set())
        try:
            entered.wait()
            if future.done():
                future.result()
                pytest.fail("insertion did not reach the controlled interleaving")
            _assert_competing_lock_is_held(store, data["content"])
        finally:
            release.set()
        first, inserted = future.result()
    assert inserted
    assert insert_exact(store, data) == (first, False)


def _assert_competing_lock_is_held(store, content):
    if isinstance(store, SqliteMemoryStore):
        registry = store._connection_registry
        with sqlite3.connect(
            registry._target, uri=registry._uri, timeout=0
        ) as observer:
            try:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    observer.execute("BEGIN IMMEDIATE")
            finally:
                observer.rollback()
        observer.close()
        return
    with store._create_connection() as observer:
        with observer.transaction():
            row = observer.execute(
                "SELECT pg_try_advisory_xact_lock("
                "hashtext('Cortex exact memory'), hashtext(%s)) AS acquired",
                (content,),
            ).fetchone()
            assert row["acquired"] is False


def test_failed_insert_rolls_back_and_connection_remains_usable(store, monkeypatch):
    name = (
        "_insert_memory_rows"
        if isinstance(store, SqliteMemoryStore)
        else "_insert_memory_on"
    )
    original = getattr(store, name)

    def fail(*args):
        original(*args)
        raise ValueError("injected failure after insert")

    with monkeypatch.context() as patch:
        patch.setattr(store, name, fail)
        with pytest.raises(ValueError, match="injected failure"):
            insert_exact(store, {"content": "rollback replay"})
    row = store._execute(
        "SELECT id FROM memories WHERE content = %s", ("rollback replay",)
    ).fetchone()
    assert row is None
    assert insert_exact(store, {"content": "rollback replay"})[1]


def test_sqlite_index_allows_unregistered_raw_writers(tmp_path):
    path = tmp_path / "raw-writer.db"
    backend = SqliteMemoryStore(str(path))
    backend._conn.execute(
        "CREATE INDEX idx_memories_exact_content ON memories "
        "(md5(content)) WHERE superseded_by_id IS NULL"
    )
    backend._conn.commit()
    backend.close()
    backend = SqliteMemoryStore(str(path))
    try:
        memory_id = backend.insert_memory({"content": "before raw edit"})
        with sqlite3.connect(path) as raw:
            raw.execute(
                "UPDATE memories SET content = ? WHERE id = ?", ("raw edit", memory_id)
            )
            raw.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        raw.close()
        assert backend.get_memory(memory_id) is None
    finally:
        backend.close()


def test_sqlite_refuses_nested_write_without_committing_caller(tmp_path):
    backend = SqliteMemoryStore(str(tmp_path / "nested.db"))
    try:
        backend._conn.execute("BEGIN")
        backend._conn.execute(
            "INSERT INTO memories (content) VALUES (%s)", ("caller work",)
        )
        with pytest.raises(RuntimeError, match="idle SQLite connection"):
            insert_exact(backend, {"content": "nested replay"})
        backend._conn.rollback()
        assert not backend._execute("SELECT id FROM memories").fetchall()
    finally:
        backend.close()


def test_quiet_consolidation_does_not_request_a_write_lock(store):
    store.insert_memory({"content": "only one current copy"})
    if isinstance(store, SqliteMemoryStore):
        # Separate thread -> separate request connection, with the writer still open.
        store._conn.execute("BEGIN IMMEDIATE")
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(collapse_exact, store).result()
        finally:
            store._conn.rollback()
    else:
        with store._create_connection() as writer:
            with writer.transaction():
                writer.execute("LOCK TABLE memories IN ROW EXCLUSIVE MODE")
                result = collapse_exact(store)
    assert result == {"superseded_total": 0}
