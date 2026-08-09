"""Connection + pool lifecycle mixin for PgMemoryStore.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — this module owns the psycopg connection and both Phase 5
connection pools (docs/program/phase-5-pool-admission-design.md):
    * ``_interactive_pool`` — hot-path tools (recall, remember, etc.)
    * ``_batch_pool`` — long-running writers (consolidate, wiki_pipeline)
DDL/schema-migration (compute_ddl_hash, _init_schema) lives in the
sibling ``pg_store_ddl`` module — this one is connection plumbing only.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import DictRow, dict_row
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from mcp_server.infrastructure.pg_store_host import PgStoreHost
from mcp_server.infrastructure.memory_config import get_memory_settings

import logging

# Explicit name (not __name__): _deallocate_all/_reconnect log under the
# pg_store.py facade's logger namespace, unchanged by the module split —
# preserves observable log output for any external log-name filter.
logger = logging.getLogger("mcp_server.infrastructure.pg_store")


class PgSchemaMixin(PgStoreHost):
    """Connection creation and Phase 5 connection-pool lifecycle."""

    def _create_connection(self) -> psycopg.Connection[DictRow]:
        """Create a new database connection."""
        return psycopg.Connection[DictRow].connect(
            self._url, row_factory=dict_row, autocommit=True
        )

    # ── Phase 5: connection pools ────────────────────────────────────────

    def _configure_pool_connection(self, conn: psycopg.Connection[DictRow]) -> None:
        """Pool callback: set up each checked-out connection.

        Registers the pgvector adapter so callers can bind `vector` params.
        Idempotent across checkouts because the pool holds a dedicated
        connection per worker thread.
        """
        register_vector(conn)

    def _open_interactive_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]:
        """Open the hot-path pool on first use."""

        settings = get_memory_settings()
        pool: ConnectionPool[psycopg.Connection[DictRow]] = ConnectionPool(
            conninfo=self._url,
            min_size=settings.POOL_INTERACTIVE_MIN,
            max_size=settings.POOL_INTERACTIVE_MAX,
            timeout=settings.POOL_INTERACTIVE_TIMEOUT_S,
            configure=self._configure_pool_connection,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
        return pool

    def _open_batch_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]:
        """Open the batch/long-running pool on first use."""

        settings = get_memory_settings()
        pool: ConnectionPool[psycopg.Connection[DictRow]] = ConnectionPool(
            conninfo=self._url,
            min_size=settings.POOL_BATCH_MIN,
            max_size=settings.POOL_BATCH_MAX,
            timeout=settings.POOL_BATCH_TIMEOUT_S,
            configure=self._configure_pool_connection,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
        return pool

    @property
    def interactive_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]:
        """Hot-path ConnectionPool for recall / remember / anchor / etc.

        See docs/program/phase-5-pool-admission-design.md §1.1 for the
        full tool-class table.
        """
        if self._interactive_pool is None:
            self._interactive_pool = self._open_interactive_pool()
        return self._interactive_pool

    @property
    def batch_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]:
        """Batch/long-running ConnectionPool for consolidate / wiki_pipeline /
        ingest / seed_project / backfill_memories.

        Separate resource so batch jobs cannot starve the interactive pool.
        """
        if self._batch_pool is None:
            self._batch_pool = self._open_batch_pool()
        return self._batch_pool

    @contextmanager
    def acquire_interactive(self) -> Iterator[psycopg.Connection[DictRow]]:
        """Context manager borrowing a connection from the interactive pool.

        Use this for short-lived hot-path operations. For long-running
        batch work (consolidate, wiki_pipeline) use ``acquire_batch``.
        When ``POOL_DISABLED=true`` the store's persistent ``_conn`` is
        yielded instead (pre-Phase-5 behavior, kill switch per §6).
        """

        if get_memory_settings().POOL_DISABLED:
            yield self._conn
            return
        with self.interactive_pool.connection() as conn:
            yield conn

    @contextmanager
    def acquire_batch(self) -> Iterator[psycopg.Connection[DictRow]]:
        """Context manager borrowing a connection from the batch pool."""

        if get_memory_settings().POOL_DISABLED:
            yield self._conn
            return
        with self.batch_pool.connection() as conn:
            yield conn

    def _deallocate_all(self) -> None:
        """Invalidate all prepared statements on the current connection.

        Called after schema initialization because CREATE OR REPLACE FUNCTION
        can change stored procedure signatures, making psycopg's auto-prepared
        plans stale (error: "cached plan must not change result type").
        """
        try:
            self._conn.execute("DEALLOCATE ALL")
        except Exception as exc:  # noqa: BLE001 — stale-plan flush is best-effort
            logger.debug("DEALLOCATE ALL after schema init failed: %s", exc)

    def _reconnect(self) -> None:
        """Drop the current connection and create a fresh one."""
        try:
            self._conn.close()
        except Exception as exc:  # noqa: BLE001 — the old connection is being replaced anyway
            logger.debug("close of stale connection failed during reconnect: %s", exc)
        self._conn = self._create_connection()
        register_vector(self._conn)
