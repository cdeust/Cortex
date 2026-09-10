"""Connection + pool lifecycle mixin for PgMemoryStore.

source: ADR-0565"""

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

# source: ADR-0565
logger = logging.getLogger("mcp_server.infrastructure.pg_store")


class PgSchemaMixin(PgStoreHost):
    """Connection creation and Phase 5 connection-pool lifecycle.

    source: ADR-0565"""

    def _create_connection(self) -> psycopg.Connection[DictRow]:
        """Create a new database connection."""
        return psycopg.Connection[DictRow].connect(
            self._url, row_factory=dict_row, autocommit=True
        )

    # source: ADR-0565

    def _configure_pool_connection(self, conn: psycopg.Connection[DictRow]) -> None:
        """Pool callback: set up each checked-out connection.

        source: ADR-0565"""
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

        source: ADR-0565"""
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

        source: ADR-0565"""

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

        source: ADR-0565"""
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
