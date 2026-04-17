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

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_store_auxiliary import PgAuxiliaryMixin
from mcp_server.infrastructure.pg_store_entities import PgEntityMixin
from mcp_server.infrastructure.pg_store_queries import PgQueryMixin
from mcp_server.infrastructure.pg_store_relationships import PgRelationshipMixin
from mcp_server.infrastructure.pg_store_rules import PgRuleMixin
from mcp_server.infrastructure.pg_store_stats import PgStatsMixin

logger = logging.getLogger(__name__)


def _get_database_url() -> str:
    """Get DATABASE_URL from environment or MemorySettings default."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        from mcp_server.infrastructure.memory_config import get_memory_settings

        url = get_memory_settings().DATABASE_URL
    return url


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PgMemoryStore(
    PgEntityMixin,
    PgRelationshipMixin,
    PgQueryMixin,
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
        self._interactive_pool: ConnectionPool | None = None
        self._batch_pool: ConnectionPool | None = None

    def _create_connection(self) -> psycopg.Connection:
        """Create a new database connection."""
        return psycopg.connect(self._url, row_factory=dict_row, autocommit=True)

    # ── Phase 5: connection pools ────────────────────────────────────────

    def _configure_pool_connection(self, conn: psycopg.Connection) -> None:
        """Pool callback: set up each checked-out connection.

        Registers the pgvector adapter so callers can bind `vector` params.
        Idempotent across checkouts because the pool holds a dedicated
        connection per worker thread.
        """
        register_vector(conn)

    def _open_interactive_pool(self) -> ConnectionPool:
        """Open the hot-path pool on first use."""
        from mcp_server.infrastructure.memory_config import get_memory_settings

        settings = get_memory_settings()
        pool = ConnectionPool(
            conninfo=self._url,
            min_size=settings.POOL_INTERACTIVE_MIN,
            max_size=settings.POOL_INTERACTIVE_MAX,
            timeout=settings.POOL_INTERACTIVE_TIMEOUT_S,
            configure=self._configure_pool_connection,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
        return pool

    def _open_batch_pool(self) -> ConnectionPool:
        """Open the batch/long-running pool on first use."""
        from mcp_server.infrastructure.memory_config import get_memory_settings

        settings = get_memory_settings()
        pool = ConnectionPool(
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
    def interactive_pool(self) -> ConnectionPool:
        """Hot-path ConnectionPool for recall / remember / anchor / etc.

        See docs/program/phase-5-pool-admission-design.md §1.1 for the
        full tool-class table.
        """
        if self._interactive_pool is None:
            self._interactive_pool = self._open_interactive_pool()
        return self._interactive_pool

    @property
    def batch_pool(self) -> ConnectionPool:
        """Batch/long-running ConnectionPool for consolidate / wiki_pipeline /
        ingest / seed_project / backfill_memories.

        Separate resource so batch jobs cannot starve the interactive pool.
        """
        if self._batch_pool is None:
            self._batch_pool = self._open_batch_pool()
        return self._batch_pool

    @contextmanager
    def acquire_interactive(self) -> Iterator[psycopg.Connection]:
        """Context manager borrowing a connection from the interactive pool.

        Use this for short-lived hot-path operations. For long-running
        batch work (consolidate, wiki_pipeline) use ``acquire_batch``.
        When ``POOL_DISABLED=true`` the store's persistent ``_conn`` is
        yielded instead (pre-Phase-5 behavior, kill switch per §6).
        """
        from mcp_server.infrastructure.memory_config import get_memory_settings

        if get_memory_settings().POOL_DISABLED:
            yield self._conn
            return
        with self.interactive_pool.connection() as conn:
            yield conn

    @contextmanager
    def acquire_batch(self) -> Iterator[psycopg.Connection]:
        """Context manager borrowing a connection from the batch pool."""
        from mcp_server.infrastructure.memory_config import get_memory_settings

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
        except Exception:
            pass

    def _reconnect(self) -> None:
        """Drop the current connection and create a fresh one."""
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = self._create_connection()
        register_vector(self._conn)

    def _execute(
        self, query: str | psycopg.sql.Composable, params: Any = None, **kwargs: Any
    ) -> psycopg.Cursor:
        """Execute a query with stale-plan recovery and reconnection.

        On 'cached plan must not change result type' (FeatureNotSupported):
        deallocates all prepared statements and retries once.
        On connection errors: reconnects and retries once.
        """
        try:
            return self._conn.execute(query, params, **kwargs)
        except psycopg.errors.FeatureNotSupported:
            # Stale prepared statement — invalidate all and retry
            logger.info("Stale prepared plan detected, deallocating and retrying")
            self._conn.rollback()
            self._deallocate_all()
            return self._conn.execute(query, params, **kwargs)
        except psycopg.OperationalError:
            # Connection lost — reconnect and retry
            logger.warning("Database connection lost, reconnecting")
            self._reconnect()
            return self._conn.execute(query, params, **kwargs)

    def _init_schema(self) -> None:
        """Create all tables, indexes, and stored procedures.

        Each statement runs independently — one failure doesn't
        prevent the rest from being created.
        """
        for ddl in get_all_ddl():
            try:
                self._conn.execute(ddl)
            except Exception as exc:
                logger.warning(
                    "Schema statement failed: %s — %s", ddl.split("\n")[0][:50], exc
                )
        self._conn.commit()

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
        return np.asarray(vec, dtype=np.float32).tobytes()

    # ── Memory CRUD ───────────────────────────────────────────────────

    def insert_memory(self, data: dict[str, Any]) -> int:
        """Insert a memory and return its ID."""
        now = _now_iso()
        embedding = self._bytes_to_vector(data.get("embedding"))
        # Normalize free-form dates to ISO 8601 for proper recency ranking
        raw_created = data.get("created_at")
        if raw_created and isinstance(raw_created, str) and "T" not in raw_created:
            from mcp_server.core.temporal import normalize_date_to_iso

            raw_created = normalize_date_to_iso(raw_created) or raw_created
        row = self._execute(
            """INSERT INTO memories (
                content, embedding, tags, source, domain,
                directory_context, created_at, last_accessed,
                heat_base, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency, is_benchmark, agent_context,
                is_global, stage_entered_at,
                arousal, dominant_emotion
            ) VALUES (
                %(content)s, %(embedding)s, %(tags)s::jsonb, %(source)s, %(domain)s,
                %(directory_context)s, %(created_at)s, %(last_accessed)s,
                %(heat)s, %(surprise_score)s, %(importance)s,
                %(emotional_valence)s, %(confidence)s, %(store_type)s,
                %(is_protected)s, %(consolidation_stage)s,
                %(theta_phase)s, %(encoding_strength)s,
                %(separation_index)s, %(interference_score)s,
                %(schema_match_score)s, %(schema_id)s,
                %(hippocampal_dependency)s, %(is_benchmark)s, %(agent_context)s,
                %(is_global)s, %(stage_entered_at)s,
                %(arousal)s, %(dominant_emotion)s
            ) RETURNING id""",
            {
                "content": data["content"],
                "embedding": embedding,
                "tags": json.dumps(data.get("tags", [])),
                "source": data.get("source", ""),
                "domain": data.get("domain", ""),
                "directory_context": data.get("directory_context", ""),
                "created_at": raw_created or now,
                "last_accessed": now,
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
            },
        ).fetchone()
        self._conn.commit()
        return row["id"]

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

    def get_homeostatic_factor(self, domain: str) -> float:
        """A3: fetch per-domain homeostatic factor, defaulting to 1.0.

        Readers MUST use this helper rather than querying the table
        directly — new domains arrive between homeostatic runs and have
        no row. The COALESCE-to-1.0 default preserves neutral scaling.

        Source: docs/program/phase-3-a3-migration-design.md §5.
        """
        row = self._execute(
            "SELECT COALESCE(MAX(factor), 1.0)::REAL AS factor "
            "FROM homeostatic_state WHERE domain = %s",
            (domain or "",),
        ).fetchone()
        if row is None:
            return 1.0
        try:
            return float(row["factor"])
        except (KeyError, TypeError):
            return 1.0

    def set_homeostatic_factor(self, domain: str, factor: float) -> None:
        """A3: upsert per-domain homeostatic factor (Feynman scalar-state).

        Replaces the per-row heat UPDATE pattern in the homeostatic cycle
        — one row written per cycle instead of 66K. Clamped to the
        CHECK bounds (0 < factor < 10).
        """
        clamped = max(0.01, min(9.99, float(factor)))
        self._execute(
            "INSERT INTO homeostatic_state (domain, factor, updated_at) "
            "VALUES (%s, %s, NOW()) "
            "ON CONFLICT (domain) DO UPDATE "
            "SET factor = EXCLUDED.factor, updated_at = NOW()",
            (domain or "", clamped),
        )
        self._conn.commit()

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
    ) -> list[dict[str, Any]]:
        """Call the PL/pgSQL recall_memories function.

        Returns over-fetched candidates (3x max_results) for client-side
        FlashRank reranking.
        """
        w = weights or {}
        emb = self._bytes_to_vector(query_embedding)
        rows = self._execute(
            "SELECT * FROM recall_memories("
            "  %s::TEXT, %s::vector, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,"
            "  %s::REAL, %s::INT, %s::INT,"
            "  %s::REAL, %s::REAL, %s::REAL, %s::REAL, %s::REAL,"
            "  %s::BOOLEAN"
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
            ),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search via tsvector. Returns (memory_id, score) pairs."""
        rows = self._execute(
            "SELECT id, ts_rank_cd(content_tsv, plainto_tsquery('english', %s)) AS score "
            "FROM memories "
            "WHERE content_tsv @@ plainto_tsquery('english', %s) "
            "ORDER BY score DESC LIMIT %s",
            (query, query, limit),
        ).fetchall()
        return [(r["id"], r["score"]) for r in rows]

    def search_vectors(
        self, query_embedding: bytes, top_k: int = 10, min_heat: float = 0.0
    ) -> list[tuple[int, float]]:
        """Vector KNN search via pgvector. Returns (memory_id, distance) pairs."""
        emb = self._bytes_to_vector(query_embedding)
        rows = self._execute(
            "SELECT id, embedding <=> %s AS distance "
            "FROM memories "
            "WHERE heat_base >= %s AND NOT is_stale AND embedding IS NOT NULL "
            "ORDER BY embedding <=> %s "
            "LIMIT %s",
            (emb, min_heat, emb, top_k),
        ).fetchall()
        return [(r["id"], r["distance"]) for r in rows]

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
        # Convert datetime to ISO string for compatibility
        for field in ("created_at", "last_accessed", "last_reconsolidated"):
            if isinstance(d.get(field), datetime):
                d[field] = d[field].isoformat()
        return d

    # ── Advanced server-side signals ──────────────────────────────────

    def spread_activation_memories(
        self,
        query_terms: list[str],
        decay: float = 0.65,
        threshold: float = 0.1,
        max_depth: int = 3,
        max_results: int = 50,
        min_heat: float = 0.05,
    ) -> list[tuple[int, float]]:
        """Run spread_activation_memories PL/pgSQL: query→entities→memories.

        Single server-side call replacing 4 Python round trips.
        """
        rows = self._execute(
            "SELECT * FROM spread_activation_memories("
            "  %s::TEXT[], %s::REAL, %s::REAL, %s::INT, %s::INT, %s::REAL"
            ")",
            (query_terms, decay, threshold, max_depth, max_results, min_heat),
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
            except Exception:
                pass
            self._interactive_pool = None
        if self._batch_pool is not None:
            try:
                self._batch_pool.close()
            except Exception:
                pass
            self._batch_pool = None
        self._conn.close()
