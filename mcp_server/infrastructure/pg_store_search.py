"""Search / retrieval mixin for PgMemoryStore: recall, FTS, vector KNN.

source: ADR-0566"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgSearchMixin(PgStoreHost):
    """Recall, full-text/vector search, and server-side retrieval signals."""

    # ── Search (delegates to PL/pgSQL) ────────────────────────────────

    _RECALL_MEMORIES_SQL = (
        "SELECT * FROM recall_memories("
        "  %s::TEXT, %s::vector, %s::TEXT, %s::TEXT, %s::TEXT, %s::TEXT,"
        "  %s::REAL, %s::INT, %s::INT,"
        "  %s::REAL, %s::REAL, %s::REAL, %s::REAL, %s::REAL,"
        "  %s::BOOLEAN, %s::TEXT[], %s::REAL"
        ")"
    )

    @staticmethod
    def _recall_bind_params(
        query_text: str,
        emb: Any,
        intent: str,
        domain: str | None,
        directory: str | None,
        agent_topic: str | None,
        min_heat: float,
        max_results: int,
        wrrf_k: int,
        weights: dict[str, float],
        include_globals: bool,
        trusted_origins: tuple[str, ...],
        untrusted_factor: float,
    ) -> tuple[Any, ...]:
        """Positional bind params for ``_RECALL_MEMORIES_SQL``, in call order."""
        return (
            query_text,
            emb,
            intent,
            domain,
            directory,
            agent_topic,
            min_heat,
            max_results,
            wrrf_k,
            weights.get("vector", 1.0),
            weights.get("fts", 0.5),
            weights.get("heat", 0.3),
            weights.get("ngram", 0.3),
            weights.get("recency", 0.0),
            include_globals,
            # source: ADR-0566
            list(trusted_origins),
            untrusted_factor,
        )

    def _run_recall(
        self,
        query_text: str,
        emb: Any,
        intent: str,
        domain: str | None,
        directory: str | None,
        agent_topic: str | None,
        min_heat: float,
        max_results: int,
        wrrf_k: int,
        weights: dict[str, float],
        include_globals: bool,
        trusted_origins: tuple[str, ...],
        untrusted_factor: float,
    ) -> list[dict[str, Any]]:
        """Bind, execute, and normalize one ``_RECALL_MEMORIES_SQL`` call.

        source: ADR-0566"""
        params = self._recall_bind_params(
            query_text,
            emb,
            intent,
            domain,
            directory,
            agent_topic,
            min_heat,
            max_results,
            wrrf_k,
            weights,
            include_globals,
            trusted_origins,
            untrusted_factor,
        )
        rows = self._execute(self._RECALL_MEMORIES_SQL, params).fetchall()
        # source: ADR-0566
        return [self._isoformat_datetime_fields(dict(r)) for r in rows]

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
        """Call the PL/pgSQL recall_memories function: over-fetched (3x
                max_results) candidates for client-side FlashRank reranking. See
                ``_run_recall`` for bind/execute/normalize.

        source: ADR-0566"""
        emb = self._bytes_to_vector(query_embedding)
        return self._run_recall(
            query_text,
            emb,
            intent,
            domain,
            directory,
            agent_topic,
            min_heat,
            max_results,
            wrrf_k,
            weights or {},
            include_globals,
            trusted_origins,
            untrusted_factor,
        )

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search via tsvector. Returns (memory_id, score) pairs.

        source: ADR-0566"""
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

        source: ADR-0566"""
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
