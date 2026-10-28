"""Exact duplicate write serialization and legacy consolidation (#707).

SQLite BEGIN IMMEDIATE serializes competing writers before the lookup.
PostgreSQL transaction advisory locks serialize equal digest candidates.
Equality is always checked after the digest, including every visibility axis.
source: https://www.sqlite.org/lang_transaction.html
source: https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.shared.content_digest import content_digest

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    from mcp_server.infrastructure.db_types import StoreConnection


_FIND_SQL = """
SELECT id FROM memories
WHERE md5(content) = %s AND content = %s
  AND superseded_by_id IS NULL AND NOT COALESCE(is_stale, FALSE)
  AND COALESCE(CAST(tags AS TEXT), '[]') NOT LIKE %s
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


def _params(data: dict[str, Any]) -> tuple[Any, ...]:
    return (
        content_digest(data["content"]),
        data["content"],
        '%"memory-replica"%',
        data.get("domain") or "",
        data.get("directory_context") or "",
        data.get("agent_context") or "",
        data.get("source") or "",
        data.get("write_class") or "deliberate",
        data.get("capture_origin") or "unknown",
        bool(data.get("is_global")),
        bool(data.get("is_team_decision")),
    )


def find_exact(store: MemoryStore, data: dict[str, Any]) -> int | None:
    """Read-only fast path; insertion must repeat this check under its lock."""
    if "memory-replica" in data.get("tags", []):
        return None
    row = store._execute(_FIND_SQL, _params(data)).fetchone()
    return int(row["id"]) if row else None


def insert_exact(store: MemoryStore, data: dict[str, Any]) -> tuple[int, bool]:
    """Return (id, inserted); failures roll back, never degrade to duplicate insert."""
    if "memory-replica" in data.get("tags", []):
        return store.insert_memory(data), True
    if isinstance(store, SqliteMemoryStore):
        return _insert_sqlite(store, data)
    with store.acquire_interactive() as conn:
        with conn.transaction():
            # hashtext collisions only serialize unrelated writers; equality
            # below prevents them from identifying unrelated content.
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (content_digest(data["content"]),),
            )
            row = conn.execute(
                cast("LiteralString", _FIND_SQL), _params(data)
            ).fetchone()
            if row:
                return int(row["id"]), False
            return store._insert_memory_on(conn, data), True


def _insert_sqlite(store: SqliteMemoryStore, data: dict[str, Any]) -> tuple[int, bool]:
    conn = store._conn
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(_FIND_SQL, _params(data)).fetchone()
        result = (
            (int(row["id"]), False) if row else (store._insert_memory_rows(data), True)
        )
        conn.commit()
        return result
    except BaseException:
        conn.rollback()
        raise


def duplicate_response(memory_id: int) -> dict[str, Any]:
    """A replay neither inserts nor updates tags, heat, provenance or wiki pages."""
    return {
        "stored": False,
        "action": "rejected",
        "reason": "exact_duplicate",
        "memory_id": memory_id,
    }


_COLLAPSE_SQL = """
WITH ranked AS MATERIALIZED (
    SELECT id, FIRST_VALUE(id) OVER (
        PARTITION BY md5(content), content,
            COALESCE(domain, ''), COALESCE(directory_context, ''),
            COALESCE(agent_context, ''), COALESCE(source, ''),
            COALESCE(write_class, 'deliberate'),
            COALESCE(capture_origin, 'unknown'),
            COALESCE(is_global, FALSE), COALESCE(is_team_decision, FALSE)
        ORDER BY COALESCE(is_protected, FALSE) DESC,
            COALESCE(no_decay, FALSE) DESC, heat_base DESC, created_at, id
    ) AS survivor
    FROM memories
    WHERE superseded_by_id IS NULL AND NOT COALESCE(is_stale, FALSE)
      AND COALESCE(CAST(tags AS TEXT), '[]') NOT LIKE '%"memory-replica"%' 
)
UPDATE memories SET superseded_by_id =
    (SELECT survivor FROM ranked WHERE ranked.id = memories.id)
WHERE id IN (SELECT id FROM ranked WHERE id <> survivor)
  AND superseded_by_id IS NULL
RETURNING id, superseded_by_id, is_protected, no_decay
"""


def _collapse_on(conn: StoreConnection) -> int:
    rows = conn.execute(cast("LiteralString", _COLLAPSE_SQL)).fetchall()
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
    """Supersede historical byte-identical heads without deleting their evidence."""
    if isinstance(store, SqliteMemoryStore):
        conn = store._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            count = _collapse_on(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    else:
        with store.acquire_batch() as conn:
            with conn.transaction():
                # Exclude concurrent content edits, deletes and supersessions
                # while election and pointer writes run on the same snapshot.
                conn.execute("LOCK TABLE memories IN SHARE ROW EXCLUSIVE MODE")
                count = _collapse_on(conn)
    return {"superseded_total": count}
