"""Search / retrieval mixin for PgMemoryStore: recall, FTS, vector KNN,
spreading activation, and the other server-side signals recall_pipeline
consumes.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — every method here delegates to a PL/pgSQL stored procedure or a
single read-only SELECT; grouped together because they are the "read
path" concern, as opposed to the write-path (``pg_store_write``) and
metadata-mutation (``pg_store_heat`` / ``pg_store_memory_meta``) mixins.
"""

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
            # issue #368 — the trust policy is passed IN, never imported:
            # infrastructure must not depend on core (module-inventory.md
            # dependency rules). It travels from the caller to the stored
            # procedure on every call, so neither this layer nor the SQL
            # holds a second copy of the vocabulary that could drift.
            list(trusted_origins),
            untrusted_factor,
        )

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
        FlashRank reranking. See ``_recall_bind_params`` for the bind-order
        contract this shares with ``_RECALL_MEMORIES_SQL``.

        ``trusted_origins`` / ``untrusted_factor`` carry the capture-origin
        trust policy (issue #368). They are parameters rather than imports
        because this layer may not depend on ``core`` — the caller reads them
        from ``core/capture_origin.py``. Their defaults are the identity
        transform (no origin trusted, factor 1.0 ⇒ every row multiplied by
        1.0), so an unaware caller gets the pre-#368 ranking unchanged rather
        than an accidental demotion of everything.
        """
        emb = self._bytes_to_vector(query_embedding)
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
            weights or {},
            include_globals,
            trusted_origins,
            untrusted_factor,
        )
        rows = self._execute(self._RECALL_MEMORIES_SQL, params).fetchall()
        # created_at must be ISO text, not datetime -- see
        # _isoformat_datetime_fields's docstring (mixed-type candidate lists).
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
