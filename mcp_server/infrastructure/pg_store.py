"""PostgreSQL + pgvector memory store.

Single storage backend for all memory operations.
Retrieval logic lives in PL/pgSQL stored procedures.
Benchmarks and production use the same code path.

Requires: psycopg[binary]>=3.1, pgvector>=0.3
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_store_entities import PgEntityMixin
from mcp_server.infrastructure.pg_store_relationships import PgRelationshipMixin
from mcp_server.infrastructure.pg_store_queries import PgQueryMixin
from mcp_server.infrastructure.pg_store_rules import PgRuleMixin
from mcp_server.infrastructure.pg_store_stats import PgStatsMixin
from mcp_server.infrastructure.pg_store_auxiliary import PgAuxiliaryMixin


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
        url = database_url or _get_database_url()
        self._conn = psycopg.connect(url, row_factory=dict_row, autocommit=False)
        self._init_schema()
        register_vector(self._conn)

    def _init_schema(self) -> None:
        """Create all tables, indexes, and stored procedures."""
        for ddl in get_all_ddl():
            self._conn.execute(ddl)
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
        row = self._conn.execute(
            """INSERT INTO memories (
                content, embedding, tags, source, domain,
                directory_context, created_at, last_accessed,
                heat, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency
            ) VALUES (
                %(content)s, %(embedding)s, %(tags)s::jsonb, %(source)s, %(domain)s,
                %(directory_context)s, %(created_at)s, %(last_accessed)s,
                %(heat)s, %(surprise_score)s, %(importance)s,
                %(emotional_valence)s, %(confidence)s, %(store_type)s,
                %(is_protected)s, %(consolidation_stage)s,
                %(theta_phase)s, %(encoding_strength)s,
                %(separation_index)s, %(interference_score)s,
                %(schema_match_score)s, %(schema_id)s,
                %(hippocampal_dependency)s
            ) RETURNING id""",
            {
                "content": data["content"],
                "embedding": embedding,
                "tags": json.dumps(data.get("tags", [])),
                "source": data.get("source", ""),
                "domain": data.get("domain", ""),
                "directory_context": data.get("directory_context", ""),
                "created_at": data.get("created_at", now),
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
            },
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = %s", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        return self._normalize_memory_row(row)

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        self._conn.execute(
            "UPDATE memories SET heat = %s WHERE id = %s", (heat, memory_id)
        )
        self._conn.commit()

    def update_memory_importance(self, memory_id: int, importance: float) -> None:
        self._conn.execute(
            "UPDATE memories SET importance = %s WHERE id = %s",
            (importance, memory_id),
        )
        self._conn.commit()

    def update_memory_access(self, memory_id: int) -> None:
        self._conn.execute(
            "UPDATE memories SET last_accessed = NOW(), "
            "access_count = access_count + 1 WHERE id = %s",
            (memory_id,),
        )
        self._conn.commit()

    def update_memory_metamemory(
        self, memory_id: int, access_count: int, useful_count: int, confidence: float
    ) -> None:
        self._conn.execute(
            "UPDATE memories SET access_count = %s, useful_count = %s, "
            "confidence = %s WHERE id = %s",
            (access_count, useful_count, confidence, memory_id),
        )
        self._conn.commit()

    def delete_memory(self, memory_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def set_memory_protected(self, memory_id: int, protected: bool = True) -> None:
        self._conn.execute(
            "UPDATE memories SET is_protected = %s WHERE id = %s",
            (protected, memory_id),
        )
        self._conn.commit()

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        self._conn.execute(
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
        min_heat: float = 0.05,
        max_results: int = 10,
        wrrf_k: int = 60,
        weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Call the PL/pgSQL recall_memories function.

        Returns over-fetched candidates (3x max_results) for client-side
        FlashRank reranking.
        """
        w = weights or {}
        emb = self._bytes_to_vector(query_embedding)
        rows = self._conn.execute(
            "SELECT * FROM recall_memories("
            "  %s::TEXT, %s::vector, %s::TEXT, %s::TEXT, %s::TEXT,"
            "  %s::REAL, %s::INT, %s::INT,"
            "  %s::REAL, %s::REAL, %s::REAL, %s::REAL, %s::REAL, %s::REAL"
            ")",
            (
                query_text,
                emb,
                intent,
                domain,
                directory,
                min_heat,
                max_results,
                wrrf_k,
                w.get("vector", 1.0),
                w.get("fts", 0.5),
                w.get("bm25", 0.4),
                w.get("heat", 0.3),
                w.get("ngram", 0.3),
                w.get("recency", 0.0),
            ),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search via tsvector. Returns (memory_id, score) pairs."""
        rows = self._conn.execute(
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
        rows = self._conn.execute(
            "SELECT id, embedding <=> %s AS distance "
            "FROM memories "
            "WHERE heat >= %s AND NOT is_stale AND embedding IS NOT NULL "
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
            self._conn.execute(
                "UPDATE memories SET content = %s, embedding = %s, "
                "compression_level = %s, compressed = TRUE, original_content = %s "
                "WHERE id = %s",
                (content, emb, compression_level, original_content, memory_id),
            )
        else:
            self._conn.execute(
                "UPDATE memories SET content = %s, embedding = %s, "
                "compression_level = %s, compressed = TRUE "
                "WHERE id = %s",
                (content, emb, compression_level, memory_id),
            )
        self._conn.commit()

    # ── Row normalization ─────────────────────────────────────────────

    def _normalize_memory_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalize a memory row for consistent API output."""
        d = dict(row)
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
        rows = self._conn.execute(
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
        rows = self._conn.execute(
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
        rows = self._conn.execute(
            "SELECT * FROM get_temporal_co_access(%s::REAL, %s::INT, %s::INT)",
            (window_hours, min_access, limit),
        ).fetchall()
        return [(r["mem_a"], r["mem_b"], r["proximity"]) for r in rows]

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()
