"""Opening a store runs no DDL; streaming consolidation holds no transaction.

Incident 2026-10-20 (``FATAL: sorry, too many clients already``): one
``consolidate_background`` backend sat ``idle in transaction`` for about two
hours, one ``ALTER TABLE`` waited behind it, and 89 reads queued behind the
``ALTER``. The two halves of that chain, each reproduced here against the
throwaway test database:

* ``PgQueryStreamMixin._stream_decay_cursor_chunks`` read the corpus through
  a named cursor inside ``conn.transaction()`` and yielded between fetches,
  so every consolidation stage (compression's ``encode`` per memory,
  forgetting's neighbour search per memory) ran with that transaction open.
* ``PgMemoryStore.__init__`` re-applied the whole DDL set whenever the
  recorded ``schema_meta.ddl_hash`` differed from its own. Two installs of
  different revisions sharing one database (measured 2026-10-21: the Claude
  plugin tree and the Codex wheel, both labelled 4.23.5, hash 44002703... vs
  c8674541...) flip that hash on every alternate process start, so the
  ``ALTER TABLE memories ADD COLUMN IF NOT EXISTS`` statements ran on hot
  paths. ``IF NOT EXISTS`` does not spare the AccessExclusive lock (first
  test below).

``lock_timeout`` and the thread join timeouts appear only in this harness, so
a regression fails instead of hanging the suite; they are not the fix.

Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-1112
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator

import pytest

from tests_py.conftest import _USE_PG

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

# The exact no-op migration from pg_schema.MIGRATIONS_DDL (ADR-1083): the
# column already exists on a provisioned database.
_NOOP_ALTER = (
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS "
    "is_team_decision BOOLEAN NOT NULL DEFAULT FALSE"
)
_FOREIGN_HASH = "another-install-revision"


def _url() -> str:
    return os.environ["DATABASE_URL"]


def _connect():
    return psycopg.connect(_url(), autocommit=True)


@contextmanager
def _idle_reader() -> Iterator[None]:
    """A client that read ``memories`` and left its transaction open."""
    conn = psycopg.connect(_url())
    conn.execute("SELECT 1 FROM memories LIMIT 1")
    try:
        yield
    finally:
        conn.rollback()
        conn.close()


def _noop_alter_completes() -> bool:
    """True iff the no-op ALTER gets its lock within the harness bound."""
    with _connect() as conn:
        conn.execute("SET lock_timeout = '500ms'")
        try:
            conn.execute(_NOOP_ALTER)
        except psycopg.errors.LockNotAvailable:
            return False
    return True


def _recorded_hash() -> str:
    with _connect() as conn:
        return conn.execute("SELECT ddl_hash FROM schema_meta").fetchone()[0]


def _set_recorded_hash(value: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE schema_meta SET ddl_hash = %s", (value,))


def test_noop_add_column_if_not_exists_still_queues_behind_an_idle_reader():
    """The PostgreSQL fact the incident rests on: the column exists, the
    statement would change nothing, and it still waits for AccessExclusive."""
    with _idle_reader():
        assert not _noop_alter_completes()
    assert _noop_alter_completes()


def _open_in_thread(opened: dict[str, object]) -> threading.Thread:
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — PG-only import

    def target() -> None:
        try:
            opened["store"] = PgMemoryStore(database_url=_url())
        except Exception as exc:  # noqa: BLE001 — the outcome under test
            opened["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    return worker


def test_opening_a_store_on_another_revision_runs_no_ddl_and_refuses():
    from mcp_server.infrastructure.schema_versions import SchemaError  # noqa: PLC0415 — PG-only import
    from mcp_server.infrastructure.pg_schema_fingerprint import compute_ddl_hash  # noqa: PLC0415

    opened: dict[str, object] = {}
    _set_recorded_hash(_FOREIGN_HASH)
    try:
        with _idle_reader():
            worker = _open_in_thread(opened)
            worker.join(timeout=10)
            queued_behind_reader = worker.is_alive()
        worker.join(timeout=120)
        assert not queued_behind_reader, (
            "opening a store queued DDL behind an idle transaction"
        )
        assert isinstance(opened.get("error"), SchemaError), opened
        assert _recorded_hash() == _FOREIGN_HASH, "opening a store migrated"
    finally:
        store = opened.get("store")
        if store is not None:
            store.close()  # type: ignore[attr-defined]
        _set_recorded_hash(compute_ddl_hash())


def test_explicit_migration_applies_and_records_the_revision():
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415 — PG-only import
    from mcp_server.infrastructure.pg_schema_fingerprint import compute_ddl_hash  # noqa: PLC0415

    _set_recorded_hash(_FOREIGN_HASH)
    try:
        assert apply_schema(_url()) > 0
        assert _recorded_hash() == compute_ddl_hash()
        assert apply_schema(_url()) == 0  # already current: no DDL
    finally:
        _set_recorded_hash(compute_ddl_hash())


def _insert_memories(store, count: int) -> set[int]:
    return {
        store.insert_memory(
            {
                "content": f"idle-tx stream row {i}",
                "tags": ["idle-tx"],
                "domain": "idle-tx",
                "source": "test",
                "is_protected": False,
            }
        )
        for i in range(count)
    }


def _idle_in_transaction_backends() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT count(*) FROM pg_stat_activity"
            " WHERE datname = current_database()"
            " AND state LIKE 'idle in transaction%%'"
            " AND pid <> pg_backend_pid()"
        ).fetchone()[0]


def test_decay_stream_holds_no_transaction_between_chunks():
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — PG-only import

    store = PgMemoryStore(database_url=_url())
    try:
        ids = _insert_memories(store, 3)
        chunks = store.iter_memories_for_decay(chunk_size=1)
        try:
            seen = [m["id"] for m in next(chunks)]
            # The consumer is now doing non-DB work between two chunks.
            assert _idle_in_transaction_backends() == 0
            assert _noop_alter_completes(), "a DDL waits on the paused stream"
            for chunk in chunks:
                seen.extend(m["id"] for m in chunk)
        finally:
            chunks.close()
        assert len(seen) == len(set(seen)), "a row was streamed twice"
        assert ids <= set(seen)
    finally:
        store.close()


def test_decay_stream_visits_each_live_row_once_despite_writes_mid_pass():
    """Without the cursor's snapshot, each live row is still read exactly
    once: a row the consumer rewrites is not read again, and a row deleted
    before its page is not handed back (the snapshot used to return it)."""
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — PG-only import

    store = PgMemoryStore(database_url=_url())
    try:
        ids = sorted(_insert_memories(store, 4))
        seen: list[int] = []
        for chunk in store.iter_memories_for_decay(chunk_size=1):
            for mem in chunk:
                seen.append(mem["id"])
                store.update_memory_importance(mem["id"], 0.9)
            if len(seen) == 1:
                store.delete_memory(ids[-1])
        assert seen.count(ids[0]) == 1
        assert ids[-1] not in seen
        assert set(ids[:-1]) <= set(seen)
        assert len(seen) == len(set(seen))
    finally:
        store.close()
