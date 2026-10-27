"""Chunked/streaming memory-read mixin for PgMemoryStore.

source: ADR-0561"""

from __future__ import annotations

from typing import Any, Iterator

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgQueryStreamMixin(PgStoreHost):
    """Keyset-paginated memory reads that release connections before yielding."""

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
            where = "heat_base >= %s::real "
            params: list[Any] = [min_heat]
        else:
            # heat_base is REAL (pg_schema.py). Recast the round-tripped
            # cursor value to that type so float8 adaptation cannot split ties.
            # source: https://www.psycopg.org/psycopg3/docs/basic/adapt.html#numbers-adaptation
            where = "heat_base >= %s::real AND (heat_base, id) < (%s::real, %s) "
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

    def _stream_decay_pages(self, chunk_size: int) -> "Iterator[list[dict[str, Any]]]":
        """Materialize one batch page before returning control to the consumer.

        source: ADR-0561 keyset precedent; PR776 transaction regression."""
        page = int(chunk_size)
        if page <= 0:
            raise ValueError("chunk_size must be positive")
        with self.batch_pool.connection() as conn:
            upper_id = conn.execute(
                "SELECT max(id) AS id FROM memories WHERE NOT is_stale"
            ).fetchall()[0]["id"]
        if upper_id is None:
            return
        last_id: int | None = None
        while True:
            query = (
                "SELECT * FROM memories WHERE NOT is_stale AND id <= %s "
                "ORDER BY id LIMIT %s"
                if last_id is None
                else "SELECT * FROM memories WHERE NOT is_stale AND id <= %s "
                "AND id > %s ORDER BY id LIMIT %s"
            )
            params = (upper_id, page) if last_id is None else (upper_id, last_id, page)
            with self.batch_pool.connection() as conn:
                rows = conn.execute(query, params).fetchall()
            if not rows:
                return
            chunk = [self._normalize_memory_row(dict(row)) for row in rows]
            last_id = chunk[-1]["id"]
            yield chunk
            if len(chunk) < page:
                return

    def iter_memories_for_decay(
        self,
        chunk_size: int = 1000,
    ) -> "Iterator[list[dict[str, Any]]]":
        """Read active memories in ID order, without a cross-page snapshot.

        source: ADR-0561"""
        if get_memory_settings().POOL_DISABLED:
            # Kill-switch path: materialize in one call for compat.
            yield self.get_all_memories_for_decay()
            return
        yield from self._stream_decay_pages(chunk_size)
