"""PostgreSQL + pgvector memory store.

Single storage backend for all memory operations.
Retrieval logic lives in PL/pgSQL stored procedures.
Benchmarks and production use the same code path.

Phase 5 connection pools (docs/program/phase-5-pool-admission-design.md):
    * ``_interactive_pool`` — hot-path tools (recall, remember, etc.)
    * ``_batch_pool`` — long-running writers (consolidate, wiki_pipeline)
    * ``_conn`` — persistent single connection kept for backward compat
      with 281 existing call sites. New code should use
      ``acquire_interactive()`` / ``acquire_batch()`` context managers.

Requires: psycopg[binary]>=3.1, psycopg_pool>=3.2, pgvector>=0.3
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator, cast

import numpy as np
import psycopg
from psycopg import sql
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_store_host import MaterializedCursor
from mcp_server.infrastructure.pg_store_auxiliary import PgAuxiliaryMixin
from mcp_server.infrastructure.pg_store_entities import PgEntityMixin
from mcp_server.infrastructure.pg_store_entity_merge import PgEntityMergeMixin
from mcp_server.infrastructure.pg_store_queries import PgQueryMixin
from mcp_server.infrastructure.pg_store_receipts import PgReceiptsMixin
from mcp_server.infrastructure.pg_store_relationships import PgRelationshipMixin
from mcp_server.infrastructure.pg_store_rules import PgRuleMixin
from mcp_server.infrastructure.pg_store_stats import PgStatsMixin
from mcp_server.observability import silent_failure
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.core.temporal_normalize import normalize_date_to_iso

if TYPE_CHECKING:
    from typing_extensions import LiteralString

logger = logging.getLogger(__name__)


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── supersede_atomic operational bounds (engineering, not algorithmic) ──────
# Bounded optimistic-concurrency retry for the reconsolidation rebase. On the
# common single-writer path the first attempt commits; the bound only bites
# under concurrent supersession of the SAME chain, where each retry re-walks to
# the head another writer just moved. Exhausting it returns a 409-style conflict
# to the caller (nothing committed) rather than looping forever.
_SUPERSEDE_REBASE_ATTEMPTS = 5
# Defensive recursion guard for the chain-head walk. Chains are acyclic by
# construction — supersede_atomic only ever extends the OPEN head — so this cap
# is a cycle backstop, not a semantic limit on how many times a fact may be
# corrected.
_CHAIN_HEAD_MAX_DEPTH = 100_000


class _SupersedeCasConflictError(Exception):
    """The chain head moved under our compare-and-set.

    Raised inside the supersede_atomic transaction to force a full rollback of
    the attempt (the freshly inserted row is undone — never committed, never
    orphaned) before rebasing onto the new head and retrying.
    """


class PgMemoryStore(
    PgEntityMixin,
    PgEntityMergeMixin,
    PgRelationshipMixin,
    PgQueryMixin,
    PgReceiptsMixin,
    PgRuleMixin,
    PgStatsMixin,
    PgAuxiliaryMixin,
):
    """PostgreSQL + pgvector storage engine for Cortex memory system."""

    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or _get_database_url()
        self._conn = self._create_connection()
        self._init_schema()
        # Invalidate prepared statements after schema DDL — stored procedure
        # signatures may have changed, making cached plans stale.
        self._deallocate_all()
        register_vector(self._conn)
        # Phase 5 pools — lazy-constructed; opening on first acquire
        # avoids paying pool-open cost for short-lived usages (tests).
        self._interactive_pool: ConnectionPool[psycopg.Connection[DictRow]] | None = (
            None
        )
        self._batch_pool: ConnectionPool[psycopg.Connection[DictRow]] | None = None

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
        don't re-run it.

        Root-cause fix for the connection storm: the 47 ``MemoryStore``
        construction sites — including the per-tool PostToolUse hook and
        the viz graph build — previously each re-ran 83 DDL statements
        while HOLDING a connection on ``pg_advisory_lock``, piling dozens
        of sessions onto one lock until ``max_connections`` was exhausted
        and the indexing build starved. Recording the applied revision
        decouples migration from construction: once the DB is current,
        construction touches no lock and no DDL.

        Pre: self._conn is a live psycopg connection (autocommit).
        Post: schema is at the code's revision; advisory lock released
        even on failure (try/finally).
        """
        ddl_list = get_all_ddl()
        ddl_hash = compute_ddl_hash()

        # Fast path: DB already at this exact DDL revision. This is the
        # steady state for every construction once the DB is provisioned —
        # no lock, no DDL, so no pile-up can form.
        if self._recorded_schema_hash() == ddl_hash:
            return

        # Stale or fresh: serialize the apply. Blocking is correct here
        # because it is RARE (only on a genuine schema change), so dozens
        # of inits cannot stack up on it the way per-construction DDL did.
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

    @staticmethod
    def _now_iso() -> str:
        return _now_iso()

    # ── Embedding conversion ──────────────────────────────────────────

    @staticmethod
    def _bytes_to_vector(emb: bytes | None) -> np.ndarray | None:
        """Convert float32 bytes blob to numpy array for pgvector."""
        if emb is None:
            return None
        return np.frombuffer(emb, dtype=np.float32)

    @staticmethod
    def _vector_to_bytes(vec: Any) -> bytes | None:
        """Convert pgvector result back to float32 bytes."""
        if vec is None:
            return None
        if isinstance(vec, Vector):
            # pgvector>=0.5.0 psycopg loaders return Vector, not ndarray
            # source: pgvector-python CHANGELOG 0.5.0 (2026-07-06)
            return vec.to_numpy().tobytes()
        return np.asarray(vec, dtype=np.float32).tobytes()

    # ── Memory CRUD ───────────────────────────────────────────────────

    # Single source of truth for the memory INSERT. insert_memory() runs it on
    # a pooled autocommit connection (one row per statement); supersede_atomic()
    # runs it inside an explicit transaction so the row and its supersession
    # edge commit — or roll back — as one unit, never leaving a disconnected row.
    _INSERT_MEMORY_SQL = """INSERT INTO memories (
                content, embedding, tags, source, domain,
                directory_context, created_at, last_accessed, heat_base_set_at,
                heat_base, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency, is_benchmark, agent_context,
                is_global, stage_entered_at,
                arousal, dominant_emotion, supersedes_id,
                source_attribution, stimulus_signature, extinction_strength,
                write_class, capture_origin
            ) VALUES (
                %(content)s, %(embedding)s, %(tags)s::jsonb, %(source)s, %(domain)s,
                %(directory_context)s, %(created_at)s, %(last_accessed)s,
                %(heat_base_set_at)s,
                %(heat)s, %(surprise_score)s, %(importance)s,
                %(emotional_valence)s, %(confidence)s, %(store_type)s,
                %(is_protected)s, %(consolidation_stage)s,
                %(theta_phase)s, %(encoding_strength)s,
                %(separation_index)s, %(interference_score)s,
                %(schema_match_score)s, %(schema_id)s,
                %(hippocampal_dependency)s, %(is_benchmark)s, %(agent_context)s,
                %(is_global)s, %(stage_entered_at)s,
                %(arousal)s, %(dominant_emotion)s, %(supersedes_id)s,
                %(source_attribution)s, %(stimulus_signature)s, %(extinction_strength)s,
                %(write_class)s, %(capture_origin)s
            ) RETURNING id"""

    def _build_insert_params(self, data: dict[str, Any]) -> dict[str, Any]:
        """Map a memory record to the _INSERT_MEMORY_SQL bind parameters.

        A3 decay clock: anchor heat_base_set_at to the event date, not NOW().
        effective_heat() decays from COALESCE(heat_base_set_at, last_accessed,
        created_at); for a never-touched insert the faithful "last canonical
        touch" IS the event (created_at), so a historical-dated memory
        (import / benchmark loader) engages the SQL forgetting law instead of
        reading hours_elapsed≈0. No-op for fresh writes where created_at≈now.
        Source: docs/program/phase-3-a3-migration-design.md §3.1 (clock = last
        touch); benchmark root-cause memory 4202968.
        """
        now = _now_iso()
        embedding = self._bytes_to_vector(data.get("embedding"))
        # Normalize free-form dates to ISO 8601 for proper recency ranking.
        # No "is it already ISO?" pre-test here: deciding that is
        # normalize_date_to_iso's job, and it returns a real ISO datetime
        # unchanged. The pre-test this replaces was `"T" not in raw_created`,
        # which skipped normalization for every string merely CONTAINING a T —
        # including "8 May 2023 13:56 EST" (issue #252).
        raw_created = data.get("created_at")
        if raw_created and isinstance(raw_created, str):
            raw_created = normalize_date_to_iso(raw_created) or raw_created
        heat_base_anchor = data.get("heat_base_set_at") or raw_created or now
        return {
            "content": data["content"],
            "embedding": embedding,
            "tags": json.dumps(data.get("tags", [])),
            "source": data.get("source", ""),
            "domain": data.get("domain", ""),
            "directory_context": data.get("directory_context", ""),
            "created_at": raw_created or now,
            "last_accessed": now,
            "heat_base_set_at": heat_base_anchor,
            "heat": data.get("heat", 1.0),
            "surprise_score": data.get("surprise_score", 0.0),
            "importance": data.get("importance", 0.5),
            "emotional_valence": data.get("emotional_valence", 0.0),
            "confidence": data.get("confidence", 1.0),
            "store_type": data.get("store_type", "episodic"),
            "is_protected": data.get("is_protected", False),
            "consolidation_stage": data.get("consolidation_stage", "labile"),
            "theta_phase": data.get("theta_phase_at_encoding", 0.0),
            "encoding_strength": data.get("encoding_strength", 1.0),
            "separation_index": data.get("separation_index", 0.0),
            "interference_score": data.get("interference_score", 0.0),
            "schema_match_score": data.get("schema_match_score", 0.0),
            "schema_id": data.get("schema_id"),
            "hippocampal_dependency": data.get("hippocampal_dependency", 1.0),
            "is_benchmark": data.get("is_benchmark", False),
            "agent_context": data.get("agent_context", ""),
            "is_global": data.get("is_global", False),
            "stage_entered_at": data.get("stage_entered_at") or raw_created or now,
            "arousal": data.get("arousal", 0.0),
            "dominant_emotion": data.get("dominant_emotion", "neutral"),
            "supersedes_id": data.get("supersedes_id"),
            "source_attribution": data.get("source_attribution", "unknown"),
            # issue #365: channel-derived capture origin. Defaults to
            # "unknown" (permissive at the gate) so every existing writer
            # is unaffected; the auto-capture path passes its real origin.
            "capture_origin": data.get("capture_origin", "unknown"),
            "stimulus_signature": data.get("stimulus_signature", ""),
            "extinction_strength": data.get("extinction_strength", 0.0),
            # M-D2 (7.4): every writer resolves this explicitly BEFORE
            # calling insert_memory (mcp_server.core.write_class is the
            # single classification choke point; infrastructure/ must not
            # import core/, so this layer trusts the caller and relies on
            # the memories.write_class CHECK constraint as the DB-level
            # backstop against a value outside the four known classes).
            "write_class": data.get("write_class") or "deliberate",
        }

    def _insert_memory_on(
        self, conn: psycopg.Connection[DictRow], data: dict[str, Any]
    ) -> int:
        """Run the memory INSERT on ``conn`` WITHOUT committing.

        The caller owns the transaction boundary: insert_memory() commits on a
        pooled autocommit connection; supersede_atomic() commits or rolls back
        the row together with its supersession edge.
        """
        row = conn.execute(
            self._INSERT_MEMORY_SQL, self._build_insert_params(data)
        ).fetchone()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING id produced no row")
        return int(row["id"])

    def insert_memory(self, data: dict[str, Any]) -> int:
        """Insert a memory and return its ID."""
        row = self._execute(
            self._INSERT_MEMORY_SQL, self._build_insert_params(data)
        ).fetchone()
        self._conn.commit()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING id produced no row")
        return int(row["id"])

    def _current_chain_head(
        self, conn: psycopg.Connection[DictRow], target_id: int
    ) -> int | None:
        """Walk ``target_id``'s supersession chain to its open head.

        Follows forward ``superseded_by_id`` edges to the row whose
        superseded_by_id IS NULL — the current head. Returns that id, or None
        if ``target_id`` no longer exists. Runs on the caller's connection so
        the walk and the CAS that follows share one transaction snapshot.
        """
        row = conn.execute(
            """WITH RECURSIVE chain(id, superseded_by_id, hops) AS (
                   SELECT id, superseded_by_id, 0
                   FROM memories WHERE id = %s
                   UNION ALL
                   SELECT m.id, m.superseded_by_id, c.hops + 1
                   FROM memories m JOIN chain c ON m.id = c.superseded_by_id
                   WHERE c.hops < %s
               )
               SELECT id FROM chain
               WHERE superseded_by_id IS NULL
               ORDER BY hops DESC LIMIT 1""",
            (target_id, _CHAIN_HEAD_MAX_DEPTH),
        ).fetchone()
        return int(row["id"]) if row else None

    def supersede_atomic(
        self, data: dict[str, Any], target_id: int
    ) -> tuple[int | None, int | None]:
        """Insert ``data`` as the supersessor of ``target_id``'s head, atomically.

        Biomimetic reconsolidation (Nader, Schafe & LeDoux 2000): a corrected
        memory is reconstructed on the CURRENT trace, never left physically
        disconnected. One transaction inserts the new row (supersedes_id = the
        walked head) and stamps that head's ``superseded_by_id`` — a
        compare-and-set that lands only while the head is still open. If a
        concurrent writer moved the head between the walk and the CAS, the whole
        transaction rolls back (the insert is undone — no orphan is ever
        committed) and we REBASE: re-walk ``target_id`` to the new head and
        retry, bounded by _SUPERSEDE_REBASE_ATTEMPTS. On the common path (no
        race) the head IS ``target_id`` and the first attempt commits.

        Returns ``(new_id, head_id)`` on success — ``head_id`` is the row the
        new memory now supersedes (== ``target_id`` unless a race rebased us).
        Returns ``(None, last_head_id)`` when the bounded rebase exhausts
        (pathological contention — nothing committed; the caller rebases and
        retries), or ``(None, None)`` when the target vanished mid-write.
        """
        last_head: int | None = None
        for _ in range(_SUPERSEDE_REBASE_ATTEMPTS):
            with self.acquire_interactive() as conn:
                try:
                    with conn.transaction():
                        head_id = self._current_chain_head(conn, target_id)
                        if head_id is None:
                            return None, None
                        last_head = head_id
                        data["supersedes_id"] = head_id
                        new_id = self._insert_memory_on(conn, data)
                        rowcount = conn.execute(
                            "UPDATE memories SET superseded_by_id = %s "
                            "WHERE id = %s AND superseded_by_id IS NULL",
                            (new_id, head_id),
                        ).rowcount
                        if rowcount != 1:
                            raise _SupersedeCasConflictError()
                        self._transfer_anchor_on(conn, head_id, new_id)
                except _SupersedeCasConflictError:
                    continue
                return new_id, head_id
        return None, last_head

    @staticmethod
    def _transfer_anchor_on(
        conn: psycopg.Connection[DictRow], head_id: int, new_id: int
    ) -> None:
        """Anchor follows the chain head at supersession (decision 2026-07-07).

        A protected/anchored memory that gets superseded must keep injecting
        its CURRENT version at session start — _fetch_anchors serves chain
        heads only — so the protection flags and the anchor heat pin move to
        the new head inside the supersede transaction. GREATEST/OR semantics:
        the new row's own heat and no_decay are never lowered. The heat_base
        write is on the I2 canonical-writer allow-list
        (tests_py/invariants/test_I2_canonical_writer.py) — it cannot route
        through bump_heat_raw, which commits on its own connection while this
        transfer must stay inside the supersede transaction.
        """
        old = conn.execute(
            "SELECT no_decay, heat_base FROM memories "
            "WHERE id = %s AND is_protected = TRUE",
            (head_id,),
        ).fetchone()
        if old is None:
            return
        # heat_base first in the SET list so the I2 static scanner
        # (single-line "UPDATE memories SET heat_base") sees this writer.
        conn.execute(
            "UPDATE memories SET heat_base = GREATEST(heat_base, %s), "
            "is_protected = TRUE, no_decay = no_decay OR %s, "
            "heat_base_set_at = NOW() WHERE id = %s",
            (old["heat_base"], old["no_decay"], new_id),
        )

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM memories WHERE id = %s", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        return self._normalize_memory_row(row)

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        """Canonical A3 single-row heat writer. Delegates to bump_heat_raw.

        Retained as a thin adapter so existing call sites don't need to
        know about heat_base_set_at; the heat value semantics are
        preserved because bump_heat_raw writes heat_base + stamps the
        bump timestamp.
        Source: docs/program/phase-3-a3-migration-design.md §3.1.
        """
        self.bump_heat_raw(memory_id, heat)

    def bump_heat_raw(self, memory_id: int, new_heat_base: float) -> None:
        """A3 canonical single writer on `memories.heat_base` (invariant I2).

        Writes heat_base AND refreshes heat_base_set_at so subsequent
        effective_heat() reads compute decay from the bump timestamp,
        not the row's previous anchor. Clamped to [0, 1] defensively —
        the CHECK constraint enforces the same bound but a defensive
        clamp avoids IntegrityError round-trips for callers computing
        near-limit values.

        Source: docs/program/phase-3-a3-migration-design.md §3.1.
        Post-A3 this is the ONE canonical site that writes heat_base;
        all other writers (anchor, preemptive_context, citation bump)
        route through here.
        """
        clamped = max(0.0, min(1.0, float(new_heat_base)))
        self._execute(
            "UPDATE memories SET heat_base = %s, heat_base_set_at = NOW() "
            "WHERE id = %s",
            (clamped, memory_id),
        )
        self._conn.commit()

    def get_homeostatic_factor(self, domain: str, write_class: str = "auto") -> float:
        """A3: fetch per-(domain, write_class) homeostatic factor, default 1.0.

        Readers MUST use this helper rather than querying the table
        directly — new domains arrive between homeostatic runs and have
        no row. The COALESCE-to-1.0 default preserves neutral scaling.

        M-D3 (7.1, stratification): ``homeostatic_state``'s primary key is
        ``(domain, write_class)`` — one row per class, not one per domain.
        ``write_class`` defaults to ``"auto"`` because that is the only
        class the recall-path read query (``pg_schema.py::recall_memories``
        / ``fetch_member_stats`` / the reheat + dedup probes) ever
        resolves; every other caller of this method (currently only
        ``handlers/consolidation/homeostatic.py``) passes its class
        explicitly. See ``mcp_server.core.write_class`` for the taxonomy
        this parameter is drawn from.

        Source: docs/program/phase-3-a3-migration-design.md §5.
        """
        row = self._execute(
            "SELECT COALESCE(MAX(factor), 1.0)::REAL AS factor "
            "FROM homeostatic_state WHERE domain = %s AND write_class = %s",
            (domain or "", write_class),
        ).fetchone()
        if row is None:
            return 1.0
        try:
            return float(row["factor"])
        except (KeyError, TypeError):
            return 1.0

    def set_homeostatic_factor(
        self, domain: str, factor: float, write_class: str = "auto"
    ) -> None:
        """A3: upsert per-(domain, write_class) homeostatic factor.

        Replaces the per-row heat UPDATE pattern in the homeostatic cycle
        — one row written per cycle instead of 66K. Clamped to the
        CHECK bounds (0 < factor < 10). See ``get_homeostatic_factor`` for
        the M-D3 ``write_class`` rationale.
        """
        clamped = max(0.01, min(9.99, float(factor)))
        self._execute(
            "INSERT INTO homeostatic_state (domain, write_class, factor, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (domain, write_class) DO UPDATE "
            "SET factor = EXCLUDED.factor, updated_at = NOW()",
            (domain or "", write_class, clamped),
        )
        self._conn.commit()

    def log_homeostatic_fold(
        self,
        domain: str,
        write_class: str,
        factor: float,
        rows_folded: int,
    ) -> int:
        """M-D3 (7.1): journal a fold event — the telemetry step 1 asked for.

        The 2026-07-10 19:22 fold that re-suppressed the deliberate class
        left no queryable trace anywhere except the row-level signature on
        ``memories`` itself (``heat_base_set_at`` matching a batched
        write) — confirmed by direct SQL, not by this table, because this
        table did not exist yet. Every fold from this point forward is
        DB-queryable without reconstructing it from row timestamps.
        """
        row = self._execute(
            "INSERT INTO homeostatic_fold_log "
            "(domain, write_class, factor, rows_folded) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (domain or "", write_class, float(factor), int(rows_folded)),
        ).fetchone()
        self._conn.commit()
        return row["id"] if row else 0

    def update_memories_heat_batch(self, updates: list[tuple[int, float]]) -> int:
        """A3 batch heat writer. Writes heat_base + refreshes heat_base_set_at.

        Single ``UPDATE ... FROM UNNEST()`` statement so 60k+ updates
        become one round-trip and one commit. The homeostatic cohort
        branch is the main consumer post-A3 (decay is lazy). Returns
        the number of rows written.

        Source: issue #13 (darval); docs/program/phase-3-a3-migration-design.md §3.2.
        """
        if not updates:
            return 0
        ids = [int(u[0]) for u in updates]
        heats = [max(0.0, min(1.0, float(u[1]))) for u in updates]
        self._execute(
            "UPDATE memories AS m "
            "SET heat_base = v.new_heat_base, heat_base_set_at = NOW() "
            "FROM (SELECT UNNEST(%s::int[]) AS id, "
            "            UNNEST(%s::real[]) AS new_heat_base) AS v "
            "WHERE m.id = v.id",
            (ids, heats),
        )
        self._conn.commit()
        return len(updates)

    def update_memory_importance(self, memory_id: int, importance: float) -> None:
        self._execute(
            "UPDATE memories SET importance = %s WHERE id = %s",
            (importance, memory_id),
        )
        self._conn.commit()

    def update_memory_access(self, memory_id: int) -> None:
        self._execute(
            "UPDATE memories SET last_accessed = NOW(), "
            "access_count = access_count + 1 WHERE id = %s",
            (memory_id,),
        )
        self._conn.commit()

    def update_memory_metamemory(
        self, memory_id: int, access_count: int, useful_count: int, confidence: float
    ) -> None:
        self._execute(
            "UPDATE memories SET access_count = %s, useful_count = %s, "
            "confidence = %s WHERE id = %s",
            (access_count, useful_count, confidence, memory_id),
        )
        self._conn.commit()

    def update_memory_value(self, memory_id: int, value: float) -> None:
        """Persist a memory's learned RL value (B2). Defensive on stores whose
        `value` column predates this migration — a failed UPDATE is swallowed so
        rating/credit never breaks on an un-migrated store.

        The pre-migration case is now rare (the migration is current-schema
        baseline); an UPDATE failing today is more likely a real regression
        than a stale column, so the first such failure is logged rather than
        silently absorbed forever (see silent_failure module docstring)."""
        try:
            self._execute(
                "UPDATE memories SET value = %s WHERE id = %s",
                (value, memory_id),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("pg_store.update_memory_value")
            silent_failure.note("pg_store.update_memory_value", exc)

    def update_memory_extinction(
        self, memory_id: int, extinction_strength: float
    ) -> None:
        """Persist a memory's reversible inhibitory extinction tag (E2).

        Writes ONLY the ``extinction_strength`` scalar in [0,1]; the memory's
        content and heat_base are left untouched — extinction suppresses the
        effective retrieval weight without erasing the trace, so decaying
        (spontaneous recovery) or clearing (reinstatement) the tag restores the
        original association (Bouton 2004). Defensive on stores whose
        ``extinction_strength`` column predates this migration — a failed UPDATE
        is swallowed so deprecation never breaks on an un-migrated store.

        See ``update_memory_value`` docstring: the same rare-pre-migration
        reasoning applies, so the first failure is logged, not just swallowed."""
        try:
            e = max(0.0, min(1.0, float(extinction_strength)))
            self._execute(
                "UPDATE memories SET extinction_strength = %s WHERE id = %s",
                (e, memory_id),
            )
            self._conn.commit()
        except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("pg_store.update_memory_extinction")
            silent_failure.note("pg_store.update_memory_extinction", exc)

    # ── User mood (Bower 1981 mood-congruent recall) ──────────────────
    # The pg_recall._get_user_mood(store) bridge duck-types against
    # ``get_user_mood()`` and consumes a scalar valence in [-1, +1].
    # We expose:
    #   - get_user_mood()       → scalar float (the bridge contract)
    #   - get_user_mood_state() → {valence, arousal} dict (richer reads)
    #   - set_user_mood(v, a)   → upsert (writers / emotion classifier)
    # Returns ``None`` from get_user_mood() iff the row is genuinely
    # absent — defensive; the schema seeds a 'default' neutral row, but
    # an in-flight migration or a manually deleted row should still
    # no-op the rerank rather than crash.
    # Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).

    def get_user_mood(self, user_id: str = "default") -> float | None:
        """Return the user's current mood valence in [-1, +1], or None.

        Scalar contract matches ``mcp_server/core/pg_recall.py:_get_user_mood``
        which clamps and floats the returned value. None means "no signal" —
        the MOOD_CONGRUENT_RERANK stage no-ops in that case (Bower 1981
        requires a real mood; we never fabricate one).
        """
        row = self._execute(
            "SELECT valence FROM user_mood WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return float(row["valence"])
        except (KeyError, TypeError, ValueError):
            return None

    def get_user_mood_state(self, user_id: str = "default") -> dict[str, float] | None:
        """Return the full mood state ``{valence, arousal}`` or None.

        Reserved for future stages that consume arousal (Russell 1980
        circumplex). The MOOD_CONGRUENT_RERANK stage uses only valence
        and reads it via ``get_user_mood()``.
        """
        row = self._execute(
            "SELECT valence, arousal FROM user_mood WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return {
                "valence": float(row["valence"]),
                "arousal": float(row["arousal"]),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def set_user_mood(
        self,
        valence: float,
        arousal: float = 0.0,
        user_id: str = "default",
    ) -> None:
        """Upsert the user's mood state. Clamps both dims to [-1, +1].

        Refreshes ``updated_at`` automatically. Idempotent — repeated
        writes with the same value still bump the timestamp, which is
        the correct semantics for a "freshness of last observed mood"
        signal that downstream EMA aggregators may consult.
        """
        v = max(-1.0, min(1.0, float(valence)))
        a = max(-1.0, min(1.0, float(arousal)))
        self._execute(
            "INSERT INTO user_mood (user_id, valence, arousal, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (user_id) DO UPDATE "
            "SET valence = EXCLUDED.valence, "
            "    arousal = EXCLUDED.arousal, "
            "    updated_at = NOW()",
            (user_id, v, a),
        )
        self._conn.commit()

    def delete_memory(self, memory_id: int) -> bool:
        cur = self._execute("DELETE FROM memories WHERE id = %s", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def set_memory_protected(self, memory_id: int, protected: bool = True) -> None:
        self._execute(
            "UPDATE memories SET is_protected = %s WHERE id = %s",
            (protected, memory_id),
        )
        self._conn.commit()

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        self._execute(
            "UPDATE memories SET is_stale = %s WHERE id = %s", (stale, memory_id)
        )
        self._conn.commit()

    def set_source_attribution(self, memory_id: int, attribution: str) -> None:
        """Persist a provenance grade (I6-D6). Sole intended writer:
        handlers/validate_memory.py — see core/provenance.py for the
        verified/verifiable/unverifiable vocabulary this column now holds."""
        self._execute(
            "UPDATE memories SET source_attribution = %s WHERE id = %s",
            (attribution, memory_id),
        )
        self._conn.commit()

    def update_forgetting_pressure_accum(self, memory_id: int, accum: float) -> None:
        """Persist the permanent-circuit leaky-integrator state for one memory.

        Written every forgetting cycle (including leak-down when interference
        abates), so the accumulator carries sustained-pressure history across
        cycles — the faithful discretization of gradual Rac1 erosion.
        source: mcp_server/core/active_forgetting.py (update_pressure_accum).
        """
        self._execute(
            "UPDATE memories SET forgetting_pressure_accum = %s WHERE id = %s",
            (accum, memory_id),
        )
        self._conn.commit()

    # ── Search (delegates to PL/pgSQL) ────────────────────────────────

    def recall_memories(
        self,
        query_text: str,
        query_embedding: bytes | None,
        intent: str = "general",
        domain: str | None = None,
        directory: str | None = None,
        agent_topic: str | None = None,
        min_heat: float = 0.05,
        max_results: int = 10,
        wrrf_k: int = 60,
        weights: dict[str, float] | None = None,
        include_globals: bool = True,
        trusted_origins: tuple[str, ...] = (),
        untrusted_factor: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Call the PL/pgSQL recall_memories function.

        Returns over-fetched candidates (3x max_results) for client-side
        FlashRank reranking.

        ``trusted_origins`` / ``untrusted_factor`` carry the capture-origin
        trust policy (issue #368). They are parameters rather than imports
        because this layer may not depend on ``core`` — the caller reads them
        from ``core/capture_origin.py``. Their defaults are the identity
        transform (no origin trusted, factor 1.0 ⇒ every row multiplied by
        1.0), so an unaware caller gets the pre-#368 ranking unchanged rather
        than an accidental demotion of everything.
        """
        w = weights or {}
        emb = self._bytes_to_vector(query_embedding)
        rows = self._execute(
            "SELECT * FROM recall_memories("
            "  %s::TEXT, %s::vector, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,"
            "  %s::REAL, %s::INT, %s::INT,"
            "  %s::REAL, %s::REAL, %s::REAL, %s::REAL, %s::REAL,"
            "  %s::BOOLEAN, %s::TEXT[], %s::REAL"
            ")",
            (
                query_text,
                emb,
                intent,
                domain,
                directory,
                agent_topic,
                min_heat,
                max_results,
                wrrf_k,
                w.get("vector", 1.0),
                w.get("fts", 0.5),
                w.get("heat", 0.3),
                w.get("ngram", 0.3),
                w.get("recency", 0.0),
                include_globals,
                # issue #368 — the trust policy is passed IN, never imported:
                # infrastructure must not depend on core (module-inventory.md
                # dependency rules). It travels from the caller to the stored
                # procedure on every call, so neither this layer nor the SQL
                # holds a second copy of the vocabulary that could drift.
                list(trusted_origins),
                untrusted_factor,
            ),
        ).fetchall()
        # created_at must be ISO text, not a raw psycopg datetime -- see
        # _isoformat_datetime_fields's docstring for the incident this
        # closes (mixed-type candidate lists once spreading_activation_expand
        # appends store.get_memory() rows onto this method's output).
        return [self._isoformat_datetime_fields(dict(r)) for r in rows]

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search via tsvector. Returns (memory_id, score) pairs.

        Reads current_memories + NOT is_stale: this is a discovery channel
        whose hits are injected by callers (prospective triggers) with a
        fabricated score ABOVE the ranked results — exclusion must happen
        here, no downstream ranking can demote a superseded or stale hit.
        """
        rows = self._execute(
            "SELECT id, ts_rank_cd(content_tsv, "
            "plainto_tsquery('english', %s)) AS score "
            "FROM current_memories "
            "WHERE content_tsv @@ plainto_tsquery('english', %s) AND NOT is_stale "
            "ORDER BY score DESC LIMIT %s",
            (query, query, limit),
        ).fetchall()
        return [(r["id"], r["score"]) for r in rows]

    def search_vectors(
        self,
        query_embedding: bytes,
        top_k: int = 10,
        min_heat: float = 0.0,
        heads_only: bool = False,
    ) -> list[tuple[int, float]]:
        """Vector KNN search via pgvector. Returns (memory_id, distance) pairs.

        heads_only routes through the current_memories view (supersession
        chain heads only): the write-gate novelty helpers pass True so a
        reformulation of an already-corrected fact is not scored "not novel"
        against the dead version. Default stays False — interference/
        forgetting callers must keep seeing physical rows.
        """
        src = "current_memories" if heads_only else "memories"
        emb = self._bytes_to_vector(query_embedding)
        rows = self._execute(
            "SELECT id, embedding <=> %s AS distance "  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"FROM {src} "
            "WHERE heat_base >= %s AND NOT is_stale AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s "
            "LIMIT %s",
            (emb, min_heat, emb, top_k),
        ).fetchall()
        return [(r["id"], r["distance"]) for r in rows]

    def search_newer_neighbors(
        self,
        query_embedding: bytes,
        after: str,
        exclude_id: int,
        top_k: int = 10,
    ) -> list[tuple[float, float]]:
        """Vector neighbors created strictly after ``after``, nearest first.

        Returns ``(similarity, age_hours)`` per newer neighbor — similarity is
        ``1 - cosine_distance`` (pgvector ``<=>``) and ``age_hours`` is the
        neighbor's age from ``NOW()``. Excludes ``exclude_id`` and stale rows.

        The "newer" (retroactive) filter is the I/O half of the active-
        forgetting signal: the caller aggregates the similarities into the
        chronic noisy-OR and reads the strongest pair as the acute interferer.
        """
        emb = self._bytes_to_vector(query_embedding)
        rows = self._execute(
            "SELECT 1 - (embedding <=> %s) AS similarity, "
            "EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0 AS age_hours "
            "FROM memories "
            "WHERE created_at > %s::timestamptz AND id <> %s "
            "AND NOT is_stale AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s LIMIT %s",
            (emb, after, exclude_id, emb, top_k),
        ).fetchall()
        return [(float(r["similarity"]), float(r["age_hours"])) for r in rows]

    # ── Compression ───────────────────────────────────────────────────

    def update_memory_compression(
        self,
        memory_id: int,
        content: str,
        embedding: bytes | None,
        compression_level: int,
        original_content: str | None = None,
    ) -> None:
        emb = self._bytes_to_vector(embedding)
        if original_content is not None:
            self._execute(
                "UPDATE memories SET content = %s, embedding = %s, "
                "compression_level = %s, compressed = TRUE, original_content = %s "
                "WHERE id = %s",
                (content, emb, compression_level, original_content, memory_id),
            )
        else:
            self._execute(
                "UPDATE memories SET content = %s, embedding = %s, "
                "compression_level = %s, compressed = TRUE "
                "WHERE id = %s",
                (content, emb, compression_level, memory_id),
            )
        self._conn.commit()

    # ── Row normalization ─────────────────────────────────────────────

    # source: incident 2026-07-11 (garde x3 bench, LongMemEval), RCA in
    # ADR-0054's addendum -- recall_memories() (the WRRF path) returned
    # raw `dict(r)` rows with created_at still a psycopg
    # `datetime.datetime` object, while every other memory-row reader in
    # this class went through _normalize_memory_row and got an ISO
    # string. Both are candidate dicts that can sit in the SAME list
    # (recall_pipeline.spreading_activation_expand appends store.get_memory()
    # rows onto recall_memories()'s output for RRF blending) and reach
    # pg_recall.py::_chronological_rerank's `sorted(..., key=lambda c:
    # c.get("created_at"))` together -- `str < datetime` raises
    # unconditionally. The response schema for `recall`
    # (handlers/recall.py, "created_at": {"type": "string", "format":
    # "date-time"}) has always mandated the string form; recall_memories()
    # was the one path never honoring it. Fixed at the source (both
    # readers now share one normalizer) rather than patched at the sort.
    _DATETIME_FIELDS: tuple[str, ...] = (
        "created_at",
        "ingested_at",
        "last_accessed",
        "last_reconsolidated",
    )

    @staticmethod
    def _isoformat_datetime_fields(
        d: dict[str, Any], fields: tuple[str, ...] = _DATETIME_FIELDS
    ) -> dict[str, Any]:
        """Convert any `datetime.datetime` value in ``fields`` to ISO-8601
        text, in place.

        Precondition: none. Postcondition: for every ``f`` in ``fields``,
        ``d[f]`` is never a ``datetime.datetime`` instance -- either it was
        already something else (str, None, absent), or it is now its
        ``.isoformat()`` string. Every reader of a memory-row dict
        (WRRF candidates, direct get_memory() rows, SA-injected
        candidates) must go through this so a caller can compare/sort
        mixed-origin candidate lists without a type mismatch.
        """
        for field in fields:
            if isinstance(d.get(field), datetime):
                d[field] = d[field].isoformat()
        return d

    def _normalize_memory_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize a memory row for consistent API output.

        Post-A3 the memories table stores ``heat_base``; Python callers
        still read the dict key ``heat``. The normalizer exposes
        ``heat`` as an alias for ``heat_base`` so downstream code does
        not need to know whether the recall path went through
        effective_heat() or a direct row select.
        """
        d = dict(row)
        # A3: expose heat_base as heat for Python callers that expect
        # the pre-A3 dict key. recall_memories() already returns heat
        # (via effective_heat); this handles direct SELECT paths.
        if "heat" not in d and "heat_base" in d:
            d["heat"] = d["heat_base"]
        # Convert embedding back to bytes
        if "embedding" in d and d["embedding"] is not None:
            d["embedding"] = self._vector_to_bytes(d["embedding"])
        # Ensure tags is a list
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        return self._isoformat_datetime_fields(d)

    # ── Advanced server-side signals ──────────────────────────────────

    def spread_activation_memories(
        self,
        query_terms: list[str],
        decay: float = 0.65,
        threshold: float = 0.1,
        max_depth: int = 3,
        max_results: int = 50,
        min_heat: float = 0.05,
        domain: str | None = None,
        include_globals: bool = True,
    ) -> list[tuple[int, float]]:
        """Run spread_activation_memories PL/pgSQL: query→entities→memories.

        Single server-side call replacing 4 Python round trips.

        domain/include_globals scope the final entity->memory mapping to
        one cognitive domain (plus is_global rows when include_globals is
        True) -- mirrors recall_memories()'s p_domain/p_include_globals.
        domain=None (default) disables the filter -- see the PL/pgSQL
        function's docstring in pg_schema.py for why callers must pass
        an explicit domain (ADR-0054: measured 52.8% cross-domain
        injection when unscoped).
        """
        rows = self._execute(
            "SELECT * FROM spread_activation_memories("
            "  %s::TEXT[], %s::REAL, %s::REAL, %s::INT, %s::INT, %s::REAL,"
            "  %s::TEXT, %s::BOOLEAN"
            ")",
            (
                query_terms,
                decay,
                threshold,
                max_depth,
                max_results,
                min_heat,
                domain,
                include_globals,
            ),
        ).fetchall()
        return [(r["memory_id"], r["activation"]) for r in rows]

    def get_hot_embeddings(
        self,
        min_heat: float = 0.05,
        domain: str | None = None,
        limit: int = 500,
    ) -> list[tuple[int, Any, float]]:
        """Fetch (memory_id, embedding, heat) for Hopfield/HDC.

        Returns raw pgvector embeddings — caller converts to numpy.
        """
        rows = self._execute(
            "SELECT * FROM get_hot_embeddings(%s::REAL, %s::TEXT, %s::INT)",
            (min_heat, domain, limit),
        ).fetchall()
        return [
            (r["memory_id"], self._vector_to_bytes(r["embedding"]), r["heat"])
            for r in rows
        ]

    def get_embeddings_for_memories(self, memory_ids: list[int]) -> dict[int, bytes]:
        """Bulk fetch embeddings for a known set of memory ids.

        Single ``WHERE id = ANY(%s)`` round trip; replaces the per-id
        ``get_memory`` loop in the post-WRRF Hopfield stage. Returns a
        dict so callers can index by id without preserving order.

        NULL embeddings are filtered out — Hopfield can't use them.
        Source: refactor of ``recall_pipeline.hopfield_complete`` to
        bound PG round-trips at top_k=30.
        """
        if not memory_ids:
            return {}
        rows = self._execute(
            "SELECT id, embedding FROM memories "
            "WHERE id = ANY(%s::int[]) AND embedding IS NOT NULL",
            ([int(m) for m in memory_ids],),
        ).fetchall()
        out: dict[int, bytes] = {}
        for r in rows:
            emb = self._vector_to_bytes(r.get("embedding"))
            if emb is not None:
                out[int(r["id"])] = emb
        return out

    def get_temporal_co_access(
        self,
        window_hours: float = 2.0,
        min_access: int = 1,
        limit: int = 100,
    ) -> list[tuple[int, int, float]]:
        """Fetch memory pairs accessed within time window (for SR graph).

        Returns (mem_a, mem_b, proximity_weight) tuples.
        """
        rows = self._execute(
            "SELECT * FROM get_temporal_co_access(%s::REAL, %s::INT, %s::INT)",
            (window_hours, min_access, limit),
        ).fetchall()
        return [(r["mem_a"], r["mem_b"], r["proximity"]) for r in rows]

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        if self._interactive_pool is not None:
            try:
                self._interactive_pool.close()
            except Exception as exc:  # noqa: BLE001 — teardown continues past a failed close
                logger.debug("interactive pool close failed: %s", exc)
            self._interactive_pool = None
        if self._batch_pool is not None:
            try:
                self._batch_pool.close()
            except Exception as exc:  # noqa: BLE001 — teardown continues past a failed close
                logger.debug("batch pool close failed: %s", exc)
            self._batch_pool = None
        self._conn.close()
