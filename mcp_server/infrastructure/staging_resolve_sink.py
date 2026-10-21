"""Staging-resolve batch sink — DB-side id resolution, zero in-RAM id map.

The constant-memory writer for the entity + edge ingest path. It COPYs a
bounded batch of *names* into a session-temp staging table, then resolves ids
INSIDE PostgreSQL — ``INSERT ... SELECT ... ON CONFLICT`` for entities, and a
``JOIN`` against the committed ``entities`` table for edges. No ``name -> id``
dict ever lives in Python, so peak application RAM is O(one batch) regardless
of total entity count.

Atomicity under ``autocommit=True`` comes from the explicit
``with conn.transaction()`` — the only construct that issues BEGIN/COMMIT and
rolls the whole batch back on failure (Dijkstra D1). The temp table is declared
``ON COMMIT DELETE ROWS`` so it self-clears after each batch commits. Each
batch is one store operation (ADR-1112): the sink holds no connection.

Pure infrastructure — no core imports.

source: ADR-0618"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from mcp_server.infrastructure.store_operations import store_operation

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    import psycopg


def _write_staged(
    conn: psycopg.Connection,
    stage_ddl: LiteralString,
    copy_sql: LiteralString,
    resolve_sql: LiteralString,
    rows: list[list[Any]],
) -> int:
    """COPY ``rows`` into the session-temp stage, resolve in SQL; return the
    rows inserted (after ``ON CONFLICT`` dedup and, for edges, dropping
    dangling endpoints, so it may be < ``len(rows)``).

    The stage is declared on first use of each connection (``IF NOT EXISTS``,
    session-local, no lock on any shared table) and empties itself at commit
    (``ON COMMIT DELETE ROWS``)."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute(stage_ddl)
    with conn.transaction():  # source: ADR-0618
        with conn.cursor() as cur:
            with cur.copy(copy_sql) as cp:
                for row in rows:
                    cp.write_row(row)
            cur.execute(resolve_sql)
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


class OperationBatchSink:
    """A ``BatchSink`` whose every batch is one store operation (ADR-1112):
    no connection is held between batches, and through the broker the rows
    cross the process boundary, never SQL."""

    def __init__(self, store: Any, operation: Callable[..., int]) -> None:
        self._store = store
        self._operation = operation

    def write_batch(self, batch: list[Any]) -> int:
        if not batch:
            return 0
        return self._store.call_batch(self._operation, [list(r) for r in batch])

    def close(self) -> None:
        """Nothing to release: no connection is held between batches."""


# ── Concrete keyed-path configurations (OCP: new keyed sinks = new config) ──

# source: ADR-0618

_ENTITY_STAGE_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS _stage_entities "
    "(name text, type text, domain text, heat real) ON COMMIT DELETE ROWS"
)
_ENTITY_COPY_SQL = "COPY _stage_entities (name, type, domain, heat) FROM STDIN"
# source: ADR-0618
_ENTITY_RESOLVE_SQL = (
    "INSERT INTO entities (name, type, domain, created_at, last_accessed, heat) "
    "SELECT DISTINCT ON (LOWER(s.name), LOWER(s.domain)) s.name, s.type, "
    "       s.domain, NOW(), NOW(), s.heat "
    "FROM _stage_entities s "
    "WHERE NOT EXISTS ("
    "    SELECT 1 FROM entities e "
    "    WHERE LOWER(e.name) = LOWER(s.name) AND e.domain = LOWER(s.domain)"
    ")"
)

_EDGE_STAGE_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS _stage_edges "
    "(src_name text, dst_name text, rel_type text, weight real, domain text) "
    "ON COMMIT DELETE ROWS"
)
_EDGE_COPY_SQL = (
    "COPY _stage_edges (src_name, dst_name, rel_type, weight, domain) FROM STDIN"
)
# source: ADR-0618
_EDGE_RESOLVE_SQL = (
    "INSERT INTO relationships "
    "(source_entity_id, target_entity_id, relationship_type, weight, "
    " confidence, created_at, last_reinforced) "
    "SELECT s.id, t.id, es.rel_type, es.weight, 1.0, NOW(), NOW() "
    "FROM _stage_edges es "
    "JOIN entities s "
    "  ON LOWER(s.name) = LOWER(es.src_name) AND s.domain = LOWER(es.domain) "
    "JOIN entities t "
    "  ON LOWER(t.name) = LOWER(es.dst_name) AND t.domain = LOWER(es.domain) "
    "ON CONFLICT (source_entity_id, target_entity_id, relationship_type) "
    "DO NOTHING"
)


@store_operation
def write_staged_entities(conn: psycopg.Connection, rows: list[list[Any]]) -> int:
    """Entity rows ``(name, type, domain, heat)``, names canonical."""
    return _write_staged(
        conn, _ENTITY_STAGE_DDL, _ENTITY_COPY_SQL, _ENTITY_RESOLVE_SQL, rows
    )


@store_operation
def write_staged_edges(conn: psycopg.Connection, rows: list[list[Any]]) -> int:
    """Edge rows ``(src_name, dst_name, rel_type, weight, domain)``, names
    canonical, endpoints resolved within ``domain``."""
    return _write_staged(conn, _EDGE_STAGE_DDL, _EDGE_COPY_SQL, _EDGE_RESOLVE_SQL, rows)


def build_entity_sink(store: Any) -> OperationBatchSink:
    """Sink for entity rows ``(name, type, domain, heat)``."""
    return OperationBatchSink(store, write_staged_entities)


def build_edge_sink(store: Any) -> OperationBatchSink:
    """Sink for edge rows ``(src_name, dst_name, rel_type, weight, domain)``."""
    return OperationBatchSink(store, write_staged_edges)
