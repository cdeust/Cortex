"""Memory query mixin for PgMemoryStore: filtered reads, time-window queries."""

from __future__ import annotations

import json
from typing import Any, Iterator

import psycopg


class PgQueryMixin:
    """Read-only memory queries on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    def get_memories_for_domain(
        self, domain: str, min_heat: float = 0.05, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE (domain = %s OR is_global = TRUE) "
            "AND heat_base >= %s ORDER BY heat_base DESC LIMIT %s",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE (directory_context = %s OR is_global = TRUE) "
            "AND heat_base >= %s ORDER BY heat_base DESC",
            (directory, min_heat),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_hot_memories(
        self,
        min_heat: float = 0.7,
        limit: int = 20,
        include_benchmarks: bool = False,
    ) -> list[dict[str, Any]]:
        bench_filter = (
            "" if include_benchmarks else "AND NOT coalesce(is_benchmark, FALSE) "
        )
        if limit > 0:
            rows = self._execute(
                f"SELECT * FROM memories WHERE heat_base >= %s {bench_filter}"
                "ORDER BY heat_base DESC LIMIT %s",
                (min_heat, limit),
            ).fetchall()
        else:
            rows = self._execute(
                f"SELECT * FROM memories WHERE heat_base >= %s {bench_filter}"
                "ORDER BY heat_base DESC",
                (min_heat,),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT id, heat_base, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("embedding") is not None:
                from mcp_server.infrastructure.pg_store import PgMemoryStore

                d["embedding"] = PgMemoryStore._vector_to_bytes(d["embedding"])
            results.append(d)
        return results

    def get_all_memories_for_validation(
        self, limit: int = 1000
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE NOT is_stale "
            "ORDER BY last_accessed ASC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_created_after(
        self, iso_timestamp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE created_at >= %s "
            "ORDER BY created_at ASC LIMIT %s",
            (iso_timestamp, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_in_time_window(
        self, center_time: str, window_minutes: int
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE "
            "ABS(EXTRACT(EPOCH FROM (created_at - %s::timestamptz))) / 60 <= %s",
            (center_time, window_minutes),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_for_decay(self) -> list[dict[str, Any]]:
        rows = self._execute("SELECT * FROM memories WHERE NOT is_stale").fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def iter_memories_for_decay(
        self,
        chunk_size: int = 1000,
    ) -> "Iterator[list[dict[str, Any]]]":
        """Stream active memories in chunks via server-side cursor.

        Phase 4: replaces the single ``SELECT *`` that materialized 66K+
        rows (multi-MB per chunk) into Python memory with a chunked
        iterator. Each yielded chunk is a list of normalized memory
        dicts; callers that compute streaming stats (Welford moments
        for homeostatic) can discard each chunk before the next lands.

        Uses ``itersize=chunk_size`` on a named cursor so psycopg fetches
        rows from the server in batches rather than buffering all
        results client-side. The connection stays borrowed for the
        duration of iteration (the pool's ``with`` is held by the
        caller via the yielded generator lifetime).

        Source: docs/program/phase-5-pool-admission-design.md (Phase 4
        chunked consolidate).
        """
        from mcp_server.infrastructure.memory_config import get_memory_settings

        if get_memory_settings().POOL_DISABLED:
            # Kill-switch path: materialize in one call for compat.
            yield self.get_all_memories_for_decay()
            return

        # Batch pool: consolidate is the dominant caller; long-lived
        # connection for cursor iteration.
        with self.batch_pool.connection() as conn:
            with conn.cursor(name="decay_stream") as cur:
                cur.itersize = chunk_size
                cur.execute("SELECT * FROM memories WHERE NOT is_stale")
                chunk: list[dict[str, Any]] = []
                for row in cur:
                    chunk.append(self._normalize_memory_row(dict(row)))
                    if len(chunk) >= chunk_size:
                        yield chunk
                        chunk = []
                if chunk:
                    yield chunk

    def search_by_tag_vector(
        self,
        query_embedding: bytes | None,
        tag: str,
        domain: str | None = None,
        min_heat: float = 0.01,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Vector search filtered by tag. Returns scored memories.

        ENGRAM (arxiv 2511.12960): per-type retrieval pools guarantee
        typed memories (preference, instruction) are not drowned out.
        """
        import numpy as np

        emb = (
            np.frombuffer(query_embedding, dtype=np.float32)
            if query_embedding
            else None
        )
        if emb is not None:
            rows = self._execute(
                "SELECT *, (1.0 - (embedding <=> %s))::REAL AS score "
                "FROM memories "
                "WHERE tags @> %s::jsonb AND heat_base >= %s AND NOT is_stale "
                "AND embedding IS NOT NULL "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY embedding <=> %s LIMIT %s",
                (emb, json.dumps([tag]), min_heat, domain, domain, emb, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT *, heat_base::REAL AS score "
                "FROM memories "
                "WHERE tags @> %s::jsonb AND heat_base >= %s AND NOT is_stale "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY heat_base DESC LIMIT %s",
                (json.dumps([tag]), min_heat, domain, domain, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def delete_memories_by_tag(self, tag: str) -> int:
        """Delete all memories containing the given tag."""
        cur = self._execute(
            "DELETE FROM memories WHERE tags @> %s::jsonb",
            (json.dumps([tag]),),
        )
        self._conn.commit()
        return cur.rowcount

    # ── Phase 2: JOIN-based entity co-access / shared-entity queries ────

    def find_co_accessed_pairs(
        self, memory_ids: list[int]
    ) -> list[tuple[int, int]]:
        """Entity pairs that co-occur in any of the sampled memories.

        Replaces the Python O(N_mem × N_ent) substring scan in
        ``plasticity._find_co_accessed_pairs`` with a SQL self-join on
        ``memory_entities``. Cost: O(pairs) via the composite PK
        (memory_id, entity_id). Returns sorted-tuple form (a < b) to
        match the pre-Phase-2 caller contract.

        Precondition: Phase 0.4.5 backfill complete (I4 coverage ≥ 99%).
        Without it, the JOIN misses pairs the substring scan would find.

        Source: docs/program/phase-5-pool-admission-design.md (Phase 2
        B1 JOIN replacement); docs/invariants/cortex-invariants.md §I4.
        """
        if not memory_ids:
            return []
        rows = self._execute(
            """
            SELECT DISTINCT
                LEAST(me1.entity_id, me2.entity_id) AS a,
                GREATEST(me1.entity_id, me2.entity_id) AS b
            FROM memory_entities me1
            JOIN memory_entities me2
              ON me1.memory_id = me2.memory_id
             AND me1.entity_id < me2.entity_id
            WHERE me1.memory_id = ANY(%s::int[])
            """,
            (memory_ids,),
        ).fetchall()
        return [(int(r["a"]), int(r["b"])) for r in rows]

    def find_shared_entities(
        self, memory_id: int, entity_ids: list[int]
    ) -> list[int]:
        """Entity IDs from the candidate set that are linked to this memory.

        Replaces the Python substring scan in
        ``write_post_store._find_shared_entities`` with a SQL lookup
        on ``memory_entities``. Used by synaptic tagging (Frey & Morris
        1997) to decide which weak memories share entities with a new
        strong event.

        Precondition: Phase 0.4.5 backfill; I4 coverage ≥ 99%.

        Source: Phase 2 B2 JOIN replacement.
        """
        if not entity_ids:
            return []
        rows = self._execute(
            "SELECT entity_id FROM memory_entities "
            "WHERE memory_id = %s AND entity_id = ANY(%s::int[])",
            (memory_id, entity_ids),
        ).fetchall()
        return [int(r["entity_id"]) for r in rows]
