"""Memory query mixin for PgMemoryStore: filtered reads, time-window queries."""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost

import json
from typing import TYPE_CHECKING, Any, Iterator
from mcp_server.infrastructure.memory_config import get_memory_settings
import numpy as np

if TYPE_CHECKING:
    pass


class PgQueryMixin(PgStoreHost):
    """Read-only memory queries on PostgreSQL."""

    def get_memories_for_domain(
        self,
        domain: str,
        min_heat: float = 0.05,
        limit: int = 50,
        heads_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Shared primitive with mixed callers. heads_only routes the read
        through the current_memories view (supersession chain heads only):
        content-serving callers (recall_hierarchical, drill_down) pass True;
        maintenance callers (validate_memory) keep False to see full chains.
        """
        src = "current_memories" if heads_only else "memories"
        rows = self._execute(
            f"SELECT * FROM {src} WHERE (domain = %s OR is_global = TRUE) "  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
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
        heads_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Shared primitive with mixed callers. heads_only routes the read
        through the current_memories view (supersession chain heads only):
        content-serving callers (drill_down, write-gate struct_nov) pass
        True; maintenance/stats callers keep False.
        """
        src = "current_memories" if heads_only else "memories"
        bench_filter = (
            "" if include_benchmarks else "AND NOT coalesce(is_benchmark, FALSE) "
        )
        if limit > 0:
            rows = self._execute(
                f"SELECT * FROM {src} WHERE heat_base >= %s {bench_filter}"  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                "ORDER BY heat_base DESC LIMIT %s",
                (min_heat, limit),
            ).fetchall()
        else:
            rows = self._execute(
                f"SELECT * FROM {src} WHERE heat_base >= %s {bench_filter}"  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                "ORDER BY heat_base DESC",
                (min_heat,),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def iter_hot_memories_chunked(
        self,
        min_heat: float = 0.0,
        include_benchmarks: bool = True,
        chunk_size: int = 1000,
        columns: str = "*",
        hard_limit: int | None = None,
    ) -> "Iterator[list[dict[str, Any]]]":
        """Stream hot memories hottest-first via KEYSET pagination.

        Each batch is an independent, index-backed range scan — NOT a
        server-side cursor over ``ORDER BY heat_base DESC`` (which forces
        PG to sort the entire 500k-row table before yielding the first
        row: EXPLAIN showed ``Sort → Parallel Seq Scan``, a measured ~79 s
        upfront stall that froze the progressive warm-up). Keyset paging
        ``WHERE (heat_base, id) < (last_heat, last_id) ORDER BY heat_base
        DESC, id DESC LIMIT n`` walks the composite ``(heat_base DESC, id
        DESC)`` index forward one bounded page at a time, so the first
        batch lands in ~ms and memories warm up continuously. This is the
        standard pattern for streaming millions of rows. source: EXPLAIN
        + heat_base tie-group histogram, 2026-06-03.

        ``columns`` — explicit projection allowlist (NOT user input). The
        graph build passes only the ~34 rendered fields, EXCLUDING the
        1540-byte ``embedding`` vector (75% of row width), ``content_tsv``
        and ``original_content`` — pulling them streamed ~37 MB of unused
        vectors and paid pgvector deserialization per row.

        ``hard_limit`` — optional hottest-N subset bound (``None`` = the
        full corpus). The caller paginates to exhaustion when unset;
        per-page memory is one ``chunk_size`` batch regardless of total.
        """
        bench_filter = (
            "" if include_benchmarks else "AND NOT coalesce(is_benchmark, FALSE) "
        )
        # ``columns`` is an internal allowlist; ``chunk_size`` is cast to
        # int. Keyset values go through bound params (%s), never
        # interpolated.
        yielded = 0
        last_heat: float | None = None
        last_id: int | None = None
        cap = int(hard_limit) if hard_limit and hard_limit > 0 else None
        while True:
            page = int(chunk_size)
            if cap is not None:
                remaining = cap - yielded
                if remaining <= 0:
                    return
                page = min(page, remaining)
            if last_heat is None:
                where = "heat_base >= %s "
                params: list[Any] = [min_heat]
            else:
                # Keyset cursor: strictly-after (last_heat, last_id) in the
                # (heat_base DESC, id DESC) order. Tuple compare is index-
                # friendly with the composite index.
                where = "heat_base >= %s AND (heat_base, id) < (%s, %s) "
                params = [min_heat, last_heat, last_id]
            sql = (
                f"SELECT {columns} FROM memories WHERE {where}{bench_filter}"  # noqa: S608 — columns is the documented internal projection allowlist; page is int(); keyset values are bound parameters (docs/ASSURANCE-CASE.md §5)
                f"ORDER BY heat_base DESC, id DESC LIMIT {page}"
            )
            rows = self._execute(sql, tuple(params)).fetchall()
            if not rows:
                return
            yield [self._normalize_memory_row(dict(r)) for r in rows]
            yielded += len(rows)
            tail = rows[-1]
            last_heat = tail["heat_base"]
            last_id = tail["id"]
            if len(rows) < page:
                return

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT id, heat_base, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("embedding") is not None:
                from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

                d["embedding"] = PgMemoryStore._vector_to_bytes(d["embedding"])
            results.append(d)
        return results

    def get_all_memories_for_validation(
        self,
        limit: int = 1000,
        *,
        after_id: int = 0,
        include_stale: bool = False,
    ) -> list[dict[str, Any]]:
        """Page through memories for validation, ``id`` order (I6-D6).

        ``after_id`` is a cursor: pass the max ``id`` seen in the previous
        page to continue. Ordering is by ``id ASC`` (not ``last_accessed``)
        specifically so the cursor is stable across calls — last_accessed
        can change between pages if a validation pass itself touches rows.
        ``include_stale`` defaults False (unchanged behavior for existing
        callers — assess_coverage, change_impact); validate_memory passes
        True so a provenance re-check can rehabilitate (de-stale) a
        memory whose references all resolve again.
        """
        rows = self._execute(
            "SELECT * FROM memories WHERE id > %s AND (NOT is_stale OR %s) "
            "ORDER BY id ASC LIMIT %s",
            (after_id, include_stale, limit),
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

    def get_memories_by_tag(self, tag: str, limit: int = 20) -> list[dict[str, Any]]:
        """Most-recent-first memories carrying ``tag``.

        Replaces full-table scans that filtered by tag in Python
        (bounded-I/O audit 2026-06-09). Recency correctness is guaranteed
        by the ORDER BY; ``limit`` only bounds the scan — callers that
        skip dead entries (e.g. graph memos whose path was deleted) get
        ``limit`` candidates of headroom.
        """
        rows = self._execute(
            "SELECT * FROM memories "
            "WHERE tags @> %s::jsonb AND NOT is_stale "
            "ORDER BY created_at DESC LIMIT %s",
            (json.dumps([tag]), limit),
        ).fetchall()
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

        if get_memory_settings().POOL_DISABLED:
            # Kill-switch path: materialize in one call for compat.
            yield self.get_all_memories_for_decay()
            return

        # Batch pool: consolidate is the dominant caller; long-lived
        # connection for cursor iteration. The pool is autocommit=True, but a
        # named (server-side) cursor needs ``DECLARE CURSOR`` inside an open
        # transaction — so wrap the iteration in ``conn.transaction()`` (which
        # issues BEGIN/COMMIT even under autocommit). The read transaction also
        # gives the whole stream a single consistent snapshot.
        with self.batch_pool.connection() as conn:
            with conn.transaction():
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

        emb = (
            np.frombuffer(query_embedding, dtype=np.float32)
            if query_embedding
            else None
        )
        # current_memories (both branches): typed pool hits are inserted at
        # rank 0 by the caller — a superseded instruction/preference served
        # here would outrank its own correction, so exclusion at the source
        # is the only safe placement.
        if emb is not None:
            rows = self._execute(
                "SELECT *, (1.0 - (embedding <=> %s))::REAL AS score "
                "FROM current_memories "
                "WHERE tags @> %s::jsonb AND heat_base >= %s AND NOT is_stale "
                "AND embedding IS NOT NULL "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY embedding <=> %s LIMIT %s",
                (emb, json.dumps([tag]), min_heat, domain, domain, emb, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT *, heat_base::REAL AS score "
                "FROM current_memories "
                "WHERE tags @> %s::jsonb AND heat_base >= %s AND NOT is_stale "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY heat_base DESC LIMIT %s",
                (json.dumps([tag]), min_heat, domain, domain, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def delete_memories_by_tag(self, tag: str, domain: str | None = None) -> int:
        """Delete memories with the given tag, optionally scoped to a domain.

        precondition: tag is a non-empty string; domain is None or a non-empty string.
        postcondition: returns the number of rows removed; rows removed iff their
            tags JSONB contains [tag] AND (domain is None OR domain matches).
            domain=None preserves global-purge behavior for callers that
            actually want it (legacy contract). Caller is responsible for
            passing domain when scope matters (e.g. seed_project, which is
            per-repo by design — see issue #16).
        """
        if domain is None:
            cur = self._execute(
                "DELETE FROM memories WHERE tags @> %s::jsonb",
                (json.dumps([tag]),),
            )
        else:
            cur = self._execute(
                "DELETE FROM memories WHERE tags @> %s::jsonb AND domain = %s",
                (json.dumps([tag]), domain),
            )
        self._conn.commit()
        return cur.rowcount

    # ── Phase 2: JOIN-based entity co-access / shared-entity queries ────

    def find_co_accessed_pairs(self, memory_ids: list[int]) -> list[tuple[int, int]]:
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

    def find_shared_entities(self, memory_id: int, entity_ids: list[int]) -> list[int]:
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
