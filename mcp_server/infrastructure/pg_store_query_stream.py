"""Chunked/streaming memory-read mixin for PgMemoryStore.

source: ADR-0561"""

from __future__ import annotations

from typing import Any, Iterator

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgQueryStreamMixin(PgStoreHost):
    """Keyset-paginated streaming memory reads (no transaction spans a yield)."""

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

    def _fetch_decay_page(self, page: int, last_id: int | None) -> list[dict[str, Any]]:
        """One keyset page of active memories, on a batch-pool connection
        borrowed for this one statement (autocommit: no transaction).

        source: ADR-1112"""
        after = "" if last_id is None else "AND id > %s "
        params: tuple[Any, ...] = (page,) if last_id is None else (last_id, page)
        sql = (
            f"SELECT * FROM memories WHERE NOT is_stale {after}"  # noqa: S608 — `after` is one of two literals; values are bound parameters
            "ORDER BY id LIMIT %s"
        )
        with self.acquire_batch() as conn:
            rows = self._execute_on_conn(conn, sql, params).fetchall()
        return [self._normalize_memory_row(dict(r)) for r in rows]

    def iter_memories_for_decay(
        self,
        chunk_size: int = 1000,
    ) -> "Iterator[list[dict[str, Any]]]":
        """Stream active memories in id order, ``chunk_size`` rows per chunk.

        Keyset pagination: each chunk is one autocommit statement and the
        connection goes back to the pool before the chunk is yielded, so no
        transaction stays open while the consumer works (compression encodes,
        forgetting searches neighbours). The named cursor inside
        ``conn.transaction()`` this replaces left the backend ``idle in
        transaction`` for a whole consolidation pass, holding its lock on
        ``memories`` (incident 2026-10-20). Each row is read once: ``id`` is
        stable and only grows, so rows the consumer rewrites are not read
        again, and rows it deletes before their page are not read at all.

        source: ADR-1112"""
        page, last_id = int(chunk_size), None
        while True:
            rows = self._fetch_decay_page(page, last_id)
            if not rows:
                return
            yield rows
            if len(rows) < page:
                return
            last_id = rows[-1]["id"]
