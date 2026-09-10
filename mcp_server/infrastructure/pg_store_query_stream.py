"""Chunked/streaming memory-read mixin for PgMemoryStore.

source: ADR-0561"""

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

        source: ADR-0561"""
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

        source: ADR-0561"""
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

        source: ADR-0561"""
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

        source: ADR-0561"""
        if get_memory_settings().POOL_DISABLED:
            # Kill-switch path: materialize in one call for compat.
            yield self.get_all_memories_for_decay()
            return
        yield from self._stream_decay_cursor_chunks(chunk_size)
