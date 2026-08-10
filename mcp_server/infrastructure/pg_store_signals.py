"""Advanced server-side retrieval-signal mixin for PgMemoryStore.

Split out of pg_store_search.py (issue: the trust/provenance-term port
from #399 pushed the file to 301 lines, one over the 300-line §4.1
cap) — spreading activation, Hopfield/HDC embedding fetches, and the
temporal co-access graph feed are downstream consumers of a recall
result, not the recall/FTS/vector-search primitives themselves.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgSignalsMixin(PgStoreHost):
    """Spreading activation, Hopfield embeddings, temporal co-access."""

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
