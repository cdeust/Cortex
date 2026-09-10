"""Fire-and-forget batch-sink adapters: COPY and executemany.

Use ``CopyBatchSink`` for max-throughput bulk inserts into a table with no
conflict handling. Use ``ExecuteManyBatchSink`` when the write needs
``ON CONFLICT`` (idempotent upsert) — COPY cannot express it.

Pure infrastructure — no core imports.

source: ADR-0506"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import LiteralString

from typing import Any

from mcp_server.infrastructure.pooled_sink import (
    ConnectAcquire,
    PooledConnectionSink,
    RowAdapter,
)


class CopyBatchSink(PooledConnectionSink):
    """Bulk-insert a batch via ``COPY ... FROM STDIN``. Fire-and-forget."""

    def __init__(
        self,
        acquire: ConnectAcquire,
        *,
        copy_sql: LiteralString,
        row_adapter: RowAdapter | None = None,
    ) -> None:
        super().__init__(acquire, row_adapter)
        self._copy_sql: LiteralString = copy_sql

    def write_batch(self, batch: list[Any]) -> int:
        if not batch:
            return 0
        conn = self._ensure_conn()
        written = 0
        with conn.transaction():  # source: ADR-0506
            with conn.cursor() as cur, cur.copy(self._copy_sql) as cp:
                for item in batch:
                    cp.write_row(self._row_adapter(item))
                    written += 1
        return written


class ExecuteManyBatchSink(PooledConnectionSink):
    """Insert a batch via ``executemany`` — use for ``ON CONFLICT`` upserts.

    ``insert_sql`` should carry an ``ON CONFLICT ... DO NOTHING/UPDATE`` clause
    when idempotency on replay matters (the only correct edge-write path —
    COPY cannot upsert).
    """

    def __init__(
        self,
        acquire: ConnectAcquire,
        *,
        insert_sql: LiteralString,
        row_adapter: RowAdapter | None = None,
    ) -> None:
        super().__init__(acquire, row_adapter)
        self._insert_sql: LiteralString = insert_sql

    def write_batch(self, batch: list[Any]) -> int:
        if not batch:
            return 0
        params = [self._row_adapter(item) for item in batch]
        conn = self._ensure_conn()
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(self._insert_sql, params)
                rc = cur.rowcount
        return rc if rc and rc > 0 else len(params)
