"""DDL/schema-migration + query-execution mixin for PgMemoryStore.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — this module owns ``_execute`` (the pooled query entrypoint every
other mixin calls) and schema migration (``_init_schema``, gated on a
content hash of the DDL set). Connection/pool plumbing lives in the
sibling ``pg_store_schema`` module.

``compute_ddl_hash`` / ``read_schema_hash`` / ``_get_database_url`` are
module-level functions re-exported by ``pg_store.py`` — ``mcp_server.migrate``
(a standalone entry point that must decide "is the DB current" without
constructing a full store) imports them from that facade path.
"""

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


# Explicit name (not __name__): _execute_on_conn/_init_schema log under the
# pg_store.py facade's logger namespace, unchanged by the module split —
# preserves observable log output for any external log-name filter.
logger = logging.getLogger("mcp_server.infrastructure.pg_store")


def compute_ddl_hash() -> str:
    """SHA-256 fingerprint of the code's full ordered DDL set.

    Pre: none. Post: deterministic hex digest — same algorithm and input
    order as ``PgMemoryStore._init_schema``'s migration gate, so external
    callers (e.g. ``mcp_server.migrate``, a standalone entry point that
    must decide "is the DB current" without constructing a full store
    first) compute the identical value. Single source of truth: both
    ``_init_schema`` and this function call ``get_all_ddl()``, never a
    duplicated statement list.
    """
    return hashlib.sha256("\n".join(get_all_ddl()).encode("utf-8")).hexdigest()


def read_schema_hash(conn: psycopg.Connection[DictRow]) -> str | None:
    """Read the recorded DDL hash from ``schema_meta`` on ``conn``, or None.

    Pre: ``conn`` is a live psycopg connection opened with
    ``row_factory=dict_row`` (matches every connection this module opens —
    ``PgMemoryStore._create_connection`` and standalone probes alike).
    Post: returns the hash of the last-applied DDL revision, or None when
    ``schema_meta`` doesn't exist yet (fresh DB) or the read fails for any
    reason — both cases mean "not yet migrated to any known revision".
    Read-only; issues no DDL and leaves no aborted-transaction state
    behind on failure.
    """
    try:
        row = conn.execute("SELECT ddl_hash FROM schema_meta WHERE id = 1;").fetchone()
        return row["ddl_hash"] if row else None
    except psycopg.Error:
        return None


def _get_database_url() -> str:
    """Get DATABASE_URL from environment or MemorySettings default.

    An unexpanded ``${user_config.database_url}`` token (Claude Code passes the
    literal through if the user_config option is unset and carries no default)
    is treated as unset, so the settings default still applies.
    """
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

        Phase 5: borrows a connection from ``interactive_pool`` for each
        call so concurrent ``asyncio.to_thread`` workers are safe. Because
        the returned cursor's ``fetch*`` must complete before the
        connection is returned to the pool, we read all rows eagerly
        into an in-memory cursor surrogate.

        On 'cached plan must not change result type' (FeatureNotSupported):
        deallocates all prepared statements on the pool connection and
        retries once.
        On connection errors: recycles the pool connection and retries.

        When ``POOL_DISABLED`` is set (kill switch), falls back to the
        persistent ``_conn`` — pre-Phase-5 behavior.
        """

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
        # Single trust boundary for psycopg's LiteralString query typing:
        # every str reaching here is either a module literal or an
        # allowlist-gated build whose mechanism its site names under the
        # ruff S608 gate (docs/ASSURANCE-CASE.md §5) — values always travel
        # separately as bound params.
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

    # Advisory lock id for schema bootstrap. Two processes hitting a
    # fresh DB simultaneously (e.g. http_standalone + a worker subproc)
    # used to deadlock on the A3 migration's ALTER TABLE / CREATE INDEX
    # pair. With this lock, the second process waits for the first to
    # finish before re-running idempotent DDL.
    # source: hashlib.sha256(b'cortex_schema_a3').hexdigest() mod 2**31
    _SCHEMA_LOCK_ID = 1357020271

    # One-row table recording the content hash of the LAST-APPLIED DDL
    # set. Construction re-applies DDL only when the code's hash differs
    # from this — see ``_init_schema``. Created lazily by the first
    # migration so a fresh DB bootstraps cleanly.
    _SCHEMA_META_DDL = (
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        " id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
        " ddl_hash text NOT NULL,"
        " applied_at timestamptz NOT NULL DEFAULT now());"
    )

    def _recorded_schema_hash(self) -> str | None:
        """Return the DDL hash recorded in ``schema_meta``, or None.

        A missing ``schema_meta`` table (fresh DB) or any read error reads
        as None → the caller migrates. Single-row indexed lookup; no
        table scan, no locks. ``self._conn`` is autocommit, so a failed
        read leaves no aborted-transaction state behind. Delegates to the
        module-level ``read_schema_hash`` — see that function for the
        single source of truth shared with standalone callers.
        """
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

        Migration is gated on a content hash of the full DDL set
        (``get_all_ddl()``, a deterministic fixed-order list), recorded in
        ``schema_meta``. On an already-provisioned DB whose recorded hash
        matches the code, this is a single indexed SELECT — no advisory
        lock, no DDL re-application. DDL runs only when the hash differs
        (a fresh DB, or a code change to the schema), serialized under the
        advisory lock with a double-check so concurrent first-time inits
        don't re-run it. See ``_apply_ddl_locked`` for what happens once
        the lock is held.

        Root-cause fix for the connection storm: the 47 ``MemoryStore``
        construction sites previously each re-ran 83 DDL statements while
        HOLDING a connection on ``pg_advisory_lock``, piling dozens of
        sessions onto one lock until ``max_connections`` was exhausted.
        Recording the applied revision decouples migration from
        construction: once the DB is current, construction touches no
        lock and no DDL.

        Pre: self._conn is a live psycopg connection (autocommit).
        Post: schema is at the code's revision; advisory lock released
        even on failure (try/finally, inside ``_apply_ddl_locked``).
        """
        ddl_list = get_all_ddl()
        ddl_hash = compute_ddl_hash()

        # Fast path: DB already at this exact DDL revision. This is the
        # steady state for every construction once the DB is provisioned —
        # no lock, no DDL, so no pile-up can form.
        if self._recorded_schema_hash() == ddl_hash:
            return
        self._apply_ddl_locked(ddl_list, ddl_hash)

    def _apply_ddl_locked(self, ddl_list: list[LiteralString], ddl_hash: str) -> None:
        """Serialize DDL application under the schema advisory lock.

        Blocking is correct here because it is RARE (only on a genuine
        schema change), so dozens of inits cannot stack up on it the way
        per-construction DDL did. Always releases the lock (finally),
        even if a peer already applied the revision while we waited or a
        statement failed.
        """
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
        """Always true — pgvector is mandatory."""
        return True
