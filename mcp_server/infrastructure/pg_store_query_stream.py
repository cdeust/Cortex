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

    def _fetch_hot_page(
        self,
        min_heat: float,
        bench_filter: str,
        columns: str,
        page: int,
        last_heat: float | None,
        last_id: int | None,
    ) -> list[dict[str, Any]]:
        """One keyset page for ``iter_hot_memories_chunked``.

        ``last_heat``/``last_id`` None means the first page (no cursor
        yet). Keyset cursor: strictly-after (last_heat, last_id) in the
        (heat_base DESC, id DESC) order — tuple compare is index-friendly
        with the composite ``(heat_base DESC, id DESC)`` index. See
        ``iter_hot_memories_chunked``'s docstring for why this beats a
        server-side cursor over ``ORDER BY heat_base DESC`` here.
        """
        if last_heat is None:
            where = "heat_base >= %s "
            params: list[Any] = [min_heat]
        else:
            where = "heat_base >= %s AND (heat_base, id) < (%s, %s) "
            params = [min_heat, last_heat, last_id]
        sql = (
            f"SELECT {columns} FROM memories WHERE {where}{bench_filter}"  # noqa: S608 — columns is the documented internal projection allowlist; page is int(); keyset values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"ORDER BY heat_base DESC, id DESC LIMIT {page}"
        )
        rows = self._execute(sql, tuple(params)).fetchall()
        return [self._normalize_memory_row(dict(r)) for r in rows]

    def iter_hot_memories_chunked(
        self,
        min_heat: float = 0.0,
        include_benchmarks: bool = True,
        chunk_size: int = 1000,
        columns: str = "*",
        hard_limit: int | None = None,
    ) -> "Iterator[list[dict[str, Any]]]":
        """Stream hot memories hottest-first via KEYSET pagination.

        Index-backed range scans, NOT a server-side cursor over ``ORDER
        BY heat_base DESC`` (EXPLAIN showed a ~79s upfront sort stall on
        the full table, 2026-06-03). See ``_fetch_hot_page`` for the
        per-page keyset query and the ``columns``/allowlist contract.
        ``hard_limit`` bounds the hottest-N subset (``None`` = full
        corpus); the caller paginates to exhaustion when unset.
        """
        bench_filter = (
            "" if include_benchmarks else "AND NOT coalesce(is_benchmark, FALSE) "
        )
        yielded, last_heat, last_id = 0, None, None
        cap = int(hard_limit) if hard_limit and hard_limit > 0 else None
        while True:
            page = self._next_hot_page_size(chunk_size, cap, yielded)
            if page is None:
                return
            rows = self._fetch_hot_page(
                min_heat, bench_filter, columns, page, last_heat, last_id
            )
            if not rows:
                return
            yield rows
            yielded += len(rows)
            last_heat, last_id = rows[-1]["heat_base"], rows[-1]["id"]
            if len(rows) < page:
                return

    @staticmethod
    def _next_hot_page_size(
        chunk_size: int, cap: int | None, yielded: int
    ) -> int | None:
        """Page size for the next keyset page, or None to stop (cap reached)."""
        page = int(chunk_size)
        if cap is None:
            return page
        remaining = cap - yielded
        return min(page, remaining) if remaining > 0 else None

    def _stream_decay_cursor_chunks(
        self, chunk_size: int
    ) -> "Iterator[list[dict[str, Any]]]":
        """Server-side-cursor half of ``iter_memories_for_decay`` (pool
        enabled path).

        Uses ``itersize=chunk_size`` on a named cursor so psycopg fetches
        rows from the server in batches rather than buffering all
        results client-side. Batch pool: consolidate is the dominant
        caller; long-lived connection for cursor iteration. The pool is
        autocommit=True, but a named (server-side) cursor needs
        ``DECLARE CURSOR`` inside an open transaction — so the iteration
        wraps in ``conn.transaction()`` (issues BEGIN/COMMIT even under
        autocommit); that also gives the whole stream one consistent
        snapshot. The connection stays borrowed for the duration of
        iteration (the pool's ``with`` is held by the caller via the
        yielded generator lifetime).
        """
        with (
            self.batch_pool.connection() as conn,
            conn.transaction(),
            conn.cursor(name="decay_stream") as cur,
        ):
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
        See ``_stream_decay_cursor_chunks`` for the pool-enabled path.

        Source: docs/program/phase-5-pool-admission-design.md (Phase 4
        chunked consolidate).
        """
        if get_memory_settings().POOL_DISABLED:
            # Kill-switch path: materialize in one call for compat.
            yield self.get_all_memories_for_decay()
            return
        yield from self._stream_decay_cursor_chunks(chunk_size)
