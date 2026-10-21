"""DDL/schema-migration + query-execution mixin for PgMemoryStore.

``read_schema_hash`` / ``_get_database_url`` are
module-level functions re-exported by ``pg_store.py`` — ``mcp_server.migrate``
(a standalone entry point that must decide "is the DB current" without
constructing a full store) imports them from that facade path.

source: ADR-0545"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg import sql
from psycopg.rows import DictRow

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.pg_migrations import migrate_locked, read_state
from mcp_server.infrastructure.schema_versions import check_runtime
from mcp_server.infrastructure.store_operations import current_request_class
from mcp_server.infrastructure.pg_store_host import MaterializedCursor, PgStoreHost

if TYPE_CHECKING:
    from typing_extensions import LiteralString


# source: ADR-0545
logger = logging.getLogger("mcp_server.infrastructure.pg_store")


def read_schema_hash(conn: psycopg.Connection[DictRow]) -> str | None:
    """Read the recorded DDL hash from ``schema_meta`` on ``conn``; None only
    when the table or its row does not exist. Any other error propagates
    (ADR-1112 a failed read is never taken for "no schema").

    source: ADR-0545"""
    try:
        row = conn.execute("SELECT ddl_hash FROM schema_meta WHERE id = 1;").fetchone()
    except psycopg.errors.UndefinedTable:
        return None
    return row["ddl_hash"] if row else None


def _get_database_url() -> str:
    """Get DATABASE_URL from environment or MemorySettings default.

    source: ADR-0545"""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or "${" in url:
        url = get_memory_settings().DATABASE_URL
    return url


class PgDdlMixin(PgStoreHost):
    """Pooled query execution + DDL/schema migration on PostgreSQL."""

    def _execute(
        self, query: str | sql.Composable, params: Any = None, **kwargs: Any
    ) -> MaterializedCursor:
        """Execute a query with stale-plan recovery and reconnection.

                When ``POOL_DISABLED`` is set (kill switch), falls back to the
                persistent ``_conn`` — pre-Phase-5 behavior.

        source: ADR-0545"""

        if get_memory_settings().POOL_DISABLED:
            return self._execute_on_conn(self._conn, query, params, **kwargs)

        pool = (
            self.batch_pool
            if current_request_class() == "background"
            else self.interactive_pool
        )
        with pool.connection() as conn:
            return self._execute_on_conn(conn, query, params, **kwargs)

    def _execute_on_conn(
        self,
        conn: psycopg.Connection[DictRow],
        query: str | sql.Composable,
        params: Any,
        **kwargs: Any,
    ) -> MaterializedCursor:
        """Run a query on a given connection with retry-on-stale-plan.

        Returns a materialized cursor (rows pre-fetched) so callers can
        keep using .fetchone() / .fetchall() after the connection is
        returned to the pool.
        """
        # source: ADR-0545
        typed_query = cast("LiteralString | sql.SQL | sql.Composed", query)
        try:
            cur = conn.execute(typed_query, params, **kwargs)
        except psycopg.errors.FeatureNotSupported:
            logger.info("Stale prepared plan detected, deallocating and retrying")
            try:
                conn.rollback()
            except Exception as exc:  # noqa: BLE001 — recovery continues to the retry below
                logger.debug("rollback during stale-plan recovery failed: %s", exc)
            try:
                conn.execute("DEALLOCATE ALL")
            except Exception as exc:  # noqa: BLE001 — recovery continues to the retry below
                logger.debug(
                    "DEALLOCATE ALL during stale-plan recovery failed: %s", exc
                )
            cur = conn.execute(typed_query, params, **kwargs)
        except psycopg.OperationalError:
            logger.warning("Database connection lost on pool checkout, retrying")
            cur = conn.execute(typed_query, params, **kwargs)
        return MaterializedCursor(cur)

    def _init_schema(self) -> None:
        """Read the schema state; run DDL only on a database with no Cortex
        schema at all (first run, nothing can be reading it).

        Any other state that is not current is refused with a
        ``SchemaError`` and nothing is executed: a runtime ``ALTER TABLE ...
        IF NOT EXISTS`` takes its AccessExclusive lock before it checks
        anything and queues every later read behind any open transaction
        (incident 2026-10-20). Migrations go through the explicit step,
        ``apply_schema`` (``python -m mcp_server.migrate``).

        source: ADR-1112"""
        if not check_runtime(read_state(self._conn)):
            migrate_locked(self._conn)

    @property
    def has_vec(self) -> bool:
        """Always true — pgvector is mandatory.

        source: ADR-0545"""
        return True
