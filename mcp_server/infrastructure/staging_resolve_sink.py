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
``ON COMMIT DELETE ROWS`` so it self-clears after each batch commits.

Pure infrastructure — no core imports.

source: ADR-0618"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp_server.infrastructure.pooled_sink import (
    ConnectAcquire,
    PooledConnectionSink,
    RowAdapter,
)

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    import psycopg


class StagingResolveSink(PooledConnectionSink):
    """A ``BatchSink`` that stages names and resolves ids server-side.

    source: ADR-0618"""

    def __init__(
        self,
        acquire: ConnectAcquire,
        *,
        stage_ddl: LiteralString,
        copy_sql: LiteralString,
        resolve_sql: LiteralString,
        row_adapter: RowAdapter | None = None,
    ) -> None:
        super().__init__(acquire, row_adapter)
        self._stage_ddl: LiteralString = stage_ddl
        self._copy_sql: LiteralString = copy_sql
        self._resolve_sql: LiteralString = resolve_sql

    def _on_connect(self, conn: psycopg.Connection) -> None:
        """Declare the session-temp staging table once per borrowed connection.

        The temp table lives for the connection's session; ``ON COMMIT DELETE
        ROWS`` (in ``stage_ddl``) empties it after every batch transaction, so
        creating it once here is correct for the worker's whole lifetime.
        """
        with conn.cursor() as cur:
            cur.execute(self._stage_ddl)

    def write_batch(self, batch: list[Any]) -> int:
        """COPY ``batch`` into the stage, resolve in SQL; return rows inserted.

        After dedup (``ON CONFLICT``) and, for edges, dangling-endpoint
        filtering (the ``JOIN``), the returned count may be < ``len(batch)``.
        The pipeline's ``rows_in - rows_written`` is therefore the
        dropped-edge count the conservation test asserts on.
        """
        if not batch:
            return 0
        conn = self._ensure_conn()
        with conn.transaction():  # source: ADR-0618
            with conn.cursor() as cur:
                with cur.copy(self._copy_sql) as cp:
                    for item in batch:
                        cp.write_row(self._row_adapter(item))
                cur.execute(self._resolve_sql)
                return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


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


def build_entity_sink(acquire: ConnectAcquire) -> StagingResolveSink:
    """Sink for entity rows ``(name, type, domain, heat)`` — names canonical."""
    return StagingResolveSink(
        acquire,
        stage_ddl=_ENTITY_STAGE_DDL,
        copy_sql=_ENTITY_COPY_SQL,
        resolve_sql=_ENTITY_RESOLVE_SQL,
    )


def build_edge_sink(acquire: ConnectAcquire) -> StagingResolveSink:
    """Sink for edge rows ``(src_name, dst_name, rel_type, weight, domain)``
    — names canonical, endpoints resolved within ``domain``."""
    return StagingResolveSink(
        acquire,
        stage_ddl=_EDGE_STAGE_DDL,
        copy_sql=_EDGE_COPY_SQL,
        resolve_sql=_EDGE_RESOLVE_SQL,
    )
