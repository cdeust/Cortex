"""The ``agent_private`` column exists, defaults to shared, and round-trips.

Issue #718, slice 2 (decision of 2026-11-19 in the issue): the flag that marks
a memory private to its agent is stored on both backends before any reader
filters on it and before any writer can set it. Every existing row and every
row written without the flag stays shared, so behaviour is unchanged.

SQLite's ALTER TABLE ... DROP COLUMN (3.35+) rebuilds the pre-#718 shape from
the current schema, so the upgrade path runs for real.

source: issue #718"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _TEST_DB_URL, _USE_PG, requires_psycopg


def _write(store, content: str, **flags) -> int:
    return store.insert_memory(
        {"content": content, "source": "test", "domain": "agent-private-test", **flags}
    )


def _flag(store, memory_id: int, relation: str = "memories") -> object:
    row = store._conn.execute(
        f"SELECT agent_private FROM {relation} WHERE id = %s", (memory_id,)
    ).fetchone()
    assert row is not None, f"memory {memory_id} not found in {relation}"
    return row["agent_private"]


@pytest.fixture
def sqlite_store():
    store = SqliteMemoryStore()
    try:
        yield store
    finally:
        store.close()


def test_a_memory_written_without_the_flag_is_shared(sqlite_store):
    memory_id = _write(sqlite_store, "written by an unrooted caller")
    assert _flag(sqlite_store, memory_id) == 0
    assert sqlite_store.get_memory(memory_id)["agent_private"] is False


def test_the_flag_round_trips_through_the_store_and_the_view(sqlite_store):
    memory_id = _write(
        sqlite_store, "private to alpha", agent_context="alpha", agent_private=True
    )
    assert _flag(sqlite_store, memory_id) == 1
    assert _flag(sqlite_store, memory_id, "current_memories") == 1
    assert sqlite_store.get_memory(memory_id)["agent_private"] is True


def test_an_upgraded_database_marks_every_existing_row_shared(sqlite_store):
    older = _write(sqlite_store, "written before the column existed")
    sqlite_store._conn.execute("DROP VIEW IF EXISTS current_memories")
    sqlite_store._conn.execute("ALTER TABLE memories DROP COLUMN agent_private")
    sqlite_store._conn.commit()

    sqlite_store._init_schema()

    assert _flag(sqlite_store, older) == 0
    assert _flag(sqlite_store, older, "current_memories") == 0


@pytest.mark.skipif(not _USE_PG, reason="requires PostgreSQL")
def test_postgresql_stores_the_flag_and_defaults_it_to_shared():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    store = PgMemoryStore(database_url=_TEST_DB_URL)
    try:
        shared = _write(store, "pg shared memory")
        private = _write(
            store, "pg private memory", agent_context="alpha", agent_private=True
        )
        with store.acquire_batch() as conn:
            rows = conn.execute(
                "SELECT id, agent_private FROM current_memories WHERE id IN (%s, %s)",
                (shared, private),
            ).fetchall()
        assert {row["id"]: row["agent_private"] for row in rows} == {
            shared: False,
            private: True,
        }
    finally:
        store.close()


@requires_psycopg
def test_postgresql_insert_binds_the_flag_and_defaults_it_to_shared():
    """The PostgreSQL insert names the column and binds it, without a server."""
    from mcp_server.infrastructure.pg_store_write import PgWriteMixin

    mixin = object.__new__(PgWriteMixin)
    sql = PgWriteMixin._INSERT_MEMORY_SQL
    assert "capture_origin, agent_private" in sql
    assert "%(agent_private)s" in sql
    shared = mixin._insert_signal_fields({}, "2026-11-19T00:00:00+00:00")
    private = mixin._insert_signal_fields(
        {"agent_private": True}, "2026-11-19T00:00:00+00:00"
    )
    assert shared["agent_private"] is False
    assert private["agent_private"] is True
