"""Residual PR776 defects reproduced against main, using a private test DB.

source: issue #776; PostgreSQL transactions and advisory transaction locks.
"""

from unittest.mock import Mock

import pytest

psycopg = pytest.importorskip("psycopg")

from mcp_server.infrastructure.pg_store_ddl import PgDdlMixin  # noqa: E402
from tests_py.conftest import _USE_PG  # noqa: E402


def test_lost_write_response_is_not_replayed():
    conn = Mock()
    conn.execute.side_effect = psycopg.OperationalError("response lost after commit")
    with pytest.raises(psycopg.OperationalError):
        PgDdlMixin()._execute_on_conn(conn, "INSERT INTO memories DEFAULT VALUES", None)
    assert conn.execute.call_count == 1


@pytest.fixture
def store():
    if not _USE_PG:
        pytest.skip("requires PostgreSQL")
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    instance = PgMemoryStore()
    try:
        yield instance
    finally:
        instance.close()


def test_decay_releases_transaction_and_pool_before_yield(store):
    for index in range(3):
        store.insert_memory({"content": f"decay boundary {index}"})
    chunks = store.iter_memories_for_decay(chunk_size=1)
    try:
        assert len(next(chunks)) == 1
        held = store._conn.execute(
            "SELECT count(*) AS n FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "AND state = 'idle in transaction'"
        ).fetchone()
        assert held["n"] == 0
        stats = store.batch_pool.get_stats()
        assert stats["pool_available"] == stats["pool_size"]
    finally:
        chunks.close()


def test_failed_ddl_rolls_back_without_recording_revision(store):
    old_hash = store._recorded_schema_hash()
    try:
        with pytest.raises(psycopg.errors.UndefinedTable):
            store._apply_ddl_locked(
                [
                    "CREATE TABLE residual_migration_probe (id integer)",
                    "SELECT * FROM residual_missing_migration_table",
                ],
                "must-not-be-recorded",
            )
        assert store._recorded_schema_hash() == old_hash
        assert (
            store._conn.execute(
                "SELECT to_regclass('residual_migration_probe') AS relation"
            ).fetchone()["relation"]
            is None
        )
        assert (
            store._conn.execute(
                "SELECT count(*) AS n FROM pg_locks WHERE pid = pg_backend_pid() "
                "AND locktype = 'advisory'"
            ).fetchone()["n"]
            == 0
        )
    finally:
        store._conn.execute("DROP TABLE IF EXISTS residual_migration_probe")
        store._record_schema_hash(old_hash)


def test_missing_schema_hash_keeps_outer_transaction_usable(store):
    from mcp_server.infrastructure.pg_store_ddl import read_schema_hash

    with store._conn.transaction():
        store._conn.execute("SET LOCAL search_path = pg_catalog")
        assert read_schema_hash(store._conn) is None
        assert store._conn.execute("SELECT 42 AS value").fetchone()["value"] == 42


def test_decay_keyset_does_not_skip_after_consumer_deletes_first_page(store):
    ids = [store.insert_memory({"content": f"page boundary {n}"}) for n in range(4)]
    chunks = store.iter_memories_for_decay(chunk_size=2)
    first = next(chunks)
    assert [row["id"] for row in first] == ids[:2]
    store._conn.execute("DELETE FROM memories WHERE id = ANY(%s)", (ids[:2],))
    assert [row["id"] for chunk in chunks for row in chunk] == ids[2:]


@pytest.mark.parametrize("size", [0, -1])
def test_decay_refuses_nonpositive_page_size(store, size):
    with pytest.raises(ValueError, match="chunk_size"):
        next(store.iter_memories_for_decay(chunk_size=size))


def test_decay_pass_does_not_chase_newly_inserted_rows(store):
    original = [store.insert_memory({"content": f"original {n}"}) for n in range(3)]
    chunks = store.iter_memories_for_decay(chunk_size=1)
    seen = [next(chunks)[0]["id"]]
    store.insert_memory({"content": "inserted during decay"})
    seen.extend(row["id"] for chunk in chunks for row in chunk)
    assert seen == original


def test_store_constructor_closes_connection_on_schema_failure(monkeypatch):
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    conn = Mock()
    monkeypatch.setattr(PgMemoryStore, "_create_connection", lambda self: conn)
    monkeypatch.setattr(
        PgMemoryStore, "_init_schema", Mock(side_effect=psycopg.errors.UndefinedTable)
    )
    with pytest.raises(psycopg.errors.UndefinedTable):
        PgMemoryStore(database_url="postgresql:///unused")
    conn.close.assert_called_once()
