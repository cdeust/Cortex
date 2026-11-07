"""SQLite atomic exact-replay operations (#707).

source: https://www.sqlite.org/lang_transaction.html
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from mcp_server.infrastructure import memory_exact_sql as exact


class SqliteExactMixin:
    @contextmanager
    def _exact_transaction(self) -> Iterator[Any]:
        """Refuse nested writes without committing the caller's transaction."""
        if self._connection_registry.connection().in_transaction:
            raise RuntimeError(
                "exact replay persistence requires an idle SQLite connection"
            )
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    def find_exact_memory(self, data: dict[str, Any]) -> int | None:
        return exact.find_on(self._conn, data, True)

    def insert_memory_exact(self, data: dict[str, Any]) -> tuple[int, bool]:
        if exact.bypass(data):
            return self.insert_memory(data), True
        with self._exact_transaction() as conn:
            existing = exact.find_on(conn, data, True)
            if existing is not None:
                return existing, False
            return self._insert_memory_rows(data), True

    def collapse_exact_replays(self) -> dict[str, int]:
        candidates = self._conn.execute(exact.candidates_sql(True)).fetchall()
        if not candidates:
            return {"superseded_total": 0}
        count = 0
        with self._exact_transaction() as conn:
            for candidate in candidates:
                row = conn.execute(
                    "SELECT * FROM memories WHERE id = %s", (candidate["id"],)
                ).fetchone()
                if row:
                    count += exact.collapse_group(conn, dict(row), True)
        return {"superseded_total": count}
