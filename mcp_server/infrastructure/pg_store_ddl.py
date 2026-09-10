"""DDL/schema-migration + query-execution mixin for PgMemoryStore.

``compute_ddl_hash`` / ``read_schema_hash`` / ``_get_database_url`` are
module-level functions re-exported by ``pg_store.py`` — ``mcp_server.migrate``
(a standalone entry point that must decide "is the DB current" without
constructing a full store) imports them from that facade path.

source: ADR-0545"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import TYPE_CHECKING, Any, cast

import psycopg
from psycopg import sql
from psycopg.rows import DictRow

from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_store_host import MaterializedCursor, PgStoreHost
from mcp_server.infrastructure.memory_config import get_memory_settings

if TYPE_CHECKING:
    from typing_extensions import LiteralString


# source: ADR-0545
logger = logging.getLogger("mcp_server.infrastructure.pg_store")


def compute_ddl_hash() -> str:
    """SHA-256 fingerprint of the code's full ordered DDL set.

    source: ADR-0545"""
    return hashlib.sha256("\n".join(get_all_ddl()).encode("utf-8")).hexdigest()


def read_schema_hash(conn: psycopg.Connection[DictRow]) -> str | None:
    """Read the recorded DDL hash from ``schema_meta`` on ``conn``, or None.

    source: ADR-0545"""
    try:
        row = conn.execute("SELECT ddl_hash FROM schema_meta WHERE id = 1;").fetchone()
        return row["ddl_hash"] if row else None
    except psycopg.Error:
        return None


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

        with self.interactive_pool.connection() as conn:
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

    # source: ADR-0545
    _SCHEMA_LOCK_ID = 1357020271

    # source: ADR-0545
    _SCHEMA_META_DDL = (
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        " id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
        " ddl_hash text NOT NULL,"
        " applied_at timestamptz NOT NULL DEFAULT now());"
    )

    def _recorded_schema_hash(self) -> str | None:
        """Return the DDL hash recorded in ``schema_meta``, or None.

        source: ADR-0545"""
        return read_schema_hash(self._conn)

    def _record_schema_hash(self, ddl_hash: str) -> None:
        """Persist the just-applied DDL revision (upsert the single row)."""
        self._conn.execute(self._SCHEMA_META_DDL)
        self._conn.execute(
            "INSERT INTO schema_meta (id, ddl_hash, applied_at)"
            " VALUES (1, %s, now())"
            " ON CONFLICT (id) DO UPDATE SET"
            " ddl_hash = EXCLUDED.ddl_hash, applied_at = EXCLUDED.applied_at;",
            (ddl_hash,),
        )

    def _init_schema(self) -> None:
        """Create/upgrade tables, indexes, and stored procedures — once
                per schema REVISION, not once per ``MemoryStore``.

                Pre: self._conn is a live psycopg connection (autocommit).
                Post: schema is at the code's revision; advisory lock released
                even on failure (try/finally, inside ``_apply_ddl_locked``).

        source: ADR-0545"""
        ddl_list = get_all_ddl()
        ddl_hash = compute_ddl_hash()

        # source: ADR-0545
        if self._recorded_schema_hash() == ddl_hash:
            return
        self._apply_ddl_locked(ddl_list, ddl_hash)

    def _apply_ddl_locked(self, ddl_list: list[LiteralString], ddl_hash: str) -> None:
        """Serialize DDL application under the schema advisory lock.

        source: ADR-0545"""
        self._conn.execute("SELECT pg_advisory_lock(%s);", (self._SCHEMA_LOCK_ID,))
        try:
            # A peer may have applied the new revision while we waited.
            if self._recorded_schema_hash() == ddl_hash:
                return
            for ddl in ddl_list:
                try:
                    self._conn.execute(ddl)
                except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
                    logger.warning(
                        "Schema statement failed: %s — %s",
                        ddl.split("\n")[0][:50],
                        exc,
                    )
            self._record_schema_hash(ddl_hash)
            self._conn.commit()
        finally:
            try:
                self._conn.execute(
                    "SELECT pg_advisory_unlock(%s);", (self._SCHEMA_LOCK_ID,)
                )
                self._conn.commit()
            except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
                logger.warning("Failed to release schema advisory lock: %s", exc)

    @property
    def has_vec(self) -> bool:
        """Always true — pgvector is mandatory.

        source: ADR-0545"""
        return True
