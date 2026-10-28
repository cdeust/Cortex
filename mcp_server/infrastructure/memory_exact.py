"""Exact replay serialization and legacy cleanup (#707).

Equality includes every write scope, and ignores benchmark rows. The normalized,
heat-ranked maintenance pass in memory_dedup_exact_pass is a separate operation.
source: https://www.sqlite.org/lang_transaction.html
source: https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Iterator, cast

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    from mcp_server.infrastructure.db_types import StoreConnection


_LIVE_SQL = """
superseded_by_id IS NULL AND NOT COALESCE(is_stale, FALSE)
AND NOT COALESCE(is_benchmark, FALSE)
AND /* replica_filter */ TRUE
"""

_FIND_SQL = """
SELECT id FROM memories
WHERE md5(content) = md5(%s) AND content = %s
  AND /* live_filter */ TRUE
  AND COALESCE(domain, '') = %s
  AND COALESCE(directory_context, '') = %s
  AND COALESCE(agent_context, '') = %s
  AND COALESCE(source, '') = %s
  AND COALESCE(write_class, 'deliberate') = %s
  AND COALESCE(capture_origin, 'unknown') = %s
  AND COALESCE(is_global, FALSE) = %s
  AND COALESCE(is_team_decision, FALSE) = %s
ORDER BY id LIMIT 1
"""

# source: issue #707: table writes are unnecessary on a duplicate-free store.
_CANDIDATES_SQL = """
SELECT 1 FROM memories WHERE /* live_filter */ TRUE
GROUP BY content HAVING COUNT(*) > 1 LIMIT 1
"""

# source: issue #707: protected rows survive; ties preserve the oldest row.
_COLLAPSE_SQL = """
WITH ranked AS MATERIALIZED (
    SELECT id, FIRST_VALUE(id) OVER (
        PARTITION BY content,
            COALESCE(domain, ''), COALESCE(directory_context, ''),
            COALESCE(agent_context, ''), COALESCE(source, ''),
            COALESCE(write_class, 'deliberate'),
            COALESCE(capture_origin, 'unknown'),
            COALESCE(is_global, FALSE), COALESCE(is_team_decision, FALSE)
        ORDER BY COALESCE(is_protected, FALSE) DESC,
            COALESCE(no_decay, FALSE) DESC, heat_base DESC, created_at, id
    ) AS survivor
    FROM memories WHERE /* live_filter */ TRUE
)
UPDATE memories SET superseded_by_id = ranked.survivor
FROM ranked
WHERE memories.id = ranked.id AND ranked.id <> ranked.survivor
  AND memories.superseded_by_id IS NULL
RETURNING memories.id, memories.superseded_by_id,
    memories.is_protected, memories.no_decay
"""


def _sql(store: MemoryStore, query: str) -> LiteralString:
    """Backend JSON membership is exact and case-sensitive on both stores."""
    if isinstance(store, SqliteMemoryStore):
        predicate = (
            "NOT EXISTS (SELECT 1 FROM json_each(tags) WHERE value = 'memory-replica')"
        )
    else:
        predicate = "NOT COALESCE(tags @> '[\"memory-replica\"]'::jsonb, FALSE)"
    query = query.replace("/* live_filter */ TRUE", _LIVE_SQL)
    return cast("LiteralString", query.replace("/* replica_filter */ TRUE", predicate))


def _params(data: dict[str, Any]) -> tuple[Any, ...]:
    return (
        data["content"],
        data["content"],
        data.get("domain") or "",
        data.get("directory_context") or "",
        data.get("agent_context") or "",
        data.get("source") or "",
        data.get("write_class") or "deliberate",
        data.get("capture_origin") or "unknown",
        bool(data.get("is_global")),
        bool(data.get("is_team_decision")),
    )


def _bypass(data: dict[str, Any]) -> bool:
    return bool(data.get("is_benchmark")) or "memory-replica" in (
        data.get("tags") or []
    )


def find_exact(store: MemoryStore, data: dict[str, Any]) -> int | None:
    """Read-only fast path; repeat the lookup under the insertion lock."""
    if _bypass(data):
        return None
    row = store._execute(_sql(store, _FIND_SQL), _params(data)).fetchone()
    return int(row["id"]) if row else None


@contextmanager
def _pg_connection(
    store: MemoryStore, *, batch: bool = False
) -> Iterator[StoreConnection]:
    """A no-pool write owns a connection: threads must never share a transaction.

    source: pg_store_schema.py: acquire_interactive yields _conn when disabled.
    """
    if get_memory_settings().POOL_DISABLED:
        with store._create_connection() as conn:
            store._prepare_connection(conn)
            yield conn
        return
    acquire = store.acquire_batch if batch else store.acquire_interactive
    with acquire() as conn:
        yield conn


@contextmanager
def _sqlite_transaction(store: SqliteMemoryStore) -> Iterator[StoreConnection]:
    """Own the transaction, or refuse without committing another caller's work."""
    if store._connection_registry.connection().in_transaction:
        raise RuntimeError(
            "exact replay persistence requires an idle SQLite connection"
        )
    conn = store._conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def insert_exact(store: MemoryStore, data: dict[str, Any]) -> tuple[int, bool]:
    """Return (id, inserted); errors roll back instead of inserting a replay."""
    if _bypass(data):
        return store.insert_memory(data), True
    if isinstance(store, SqliteMemoryStore):
        with _sqlite_transaction(store) as conn:
            row = conn.execute(_sql(store, _FIND_SQL), _params(data)).fetchone()
            if row:
                return int(row["id"]), False
            return store._insert_memory_rows(data), True
    with _pg_connection(store) as conn:
        with conn.transaction():
            # Two-key locks cannot collide with the single-key schema lock.
            # source: PostgreSQL functions-admin.html#FUNCTIONS-ADVISORY-LOCKS.
            conn.execute(
                "SELECT pg_advisory_xact_lock("
                "hashtext('Cortex exact memory'), hashtext(%s))",
                (data["content"],),
            )
            row = conn.execute(_sql(store, _FIND_SQL), _params(data)).fetchone()
            if row:
                return int(row["id"]), False
            return store._insert_memory_on(conn, data), True


def _collapse_on(store: MemoryStore, conn: StoreConnection) -> int:
    rows = conn.execute(_sql(store, _COLLAPSE_SQL)).fetchall()
    for row in rows:
        if row["is_protected"] or row["no_decay"]:
            conn.execute(
                "UPDATE memories SET "
                "is_protected = COALESCE(is_protected, FALSE) OR %s, "
                "no_decay = COALESCE(no_decay, FALSE) OR %s WHERE id = %s",
                (
                    bool(row["is_protected"]),
                    bool(row["no_decay"]),
                    row["superseded_by_id"],
                ),
            )
    return len(rows)


def collapse_exact(store: MemoryStore) -> dict[str, int]:
    """Retain rows, preserve scope, and avoid write locks when no candidates exist."""
    query = _sql(store, _CANDIDATES_SQL)
    if not store._execute(query).fetchone():
        return {"superseded_total": 0}
    if isinstance(store, SqliteMemoryStore):
        with _sqlite_transaction(store) as conn:
            count = _collapse_on(store, conn)
    else:
        with _pg_connection(store, batch=True) as conn:
            with conn.transaction():
                # No unbounded lock wait in background maintenance. A busy
                # table is surfaced by consolidate's existing partial-failure boundary.
                # source: PostgreSQL LOCK documentation, NOWAIT.
                conn.execute("LOCK TABLE memories IN SHARE ROW EXCLUSIVE MODE NOWAIT")
                count = _collapse_on(store, conn)
    return {"superseded_total": count}
