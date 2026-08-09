"""Chunked/streaming memory-read mixin for PgMemoryStore.

Split out of pg_store_queries.py (issue #407: 401 lines over the
300-line §4.1 cap) — keyset-paginated and server-side-cursor streaming
reads are their own concern: bounded per-page memory, not a single
filtered SELECT.
"""

from __future__ import annotations

from typing import Any, Iterator

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgQueryStreamMixin(PgStoreHost):
    """Keyset-paginated / server-side-cursor streaming memory reads."""

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
