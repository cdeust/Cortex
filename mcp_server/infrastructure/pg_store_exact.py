"""PostgreSQL atomic exact-replay operations (#707).

Each duplicate group uses the same content advisory lock as an insertion.
source: https://www.postgresql.org/docs/current/explicit-locking.html
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from mcp_server.infrastructure import memory_exact_sql as exact
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.pg_store_host import PgStoreHost

_LOCK = "SELECT pg_advisory_xact_lock(hashtext('Cortex exact memory'), hashtext(%s))"
_TRY_LOCK = (
    "SELECT pg_try_advisory_xact_lock("
    "hashtext('Cortex exact memory'), hashtext(%s)) AS acquired"
)


class PgExactMixin(PgStoreHost):
    @contextmanager
    def _exact_connection(self) -> Iterator[Any]:
        """A disabled pool still gives each writer its own transaction."""
        if get_memory_settings().POOL_DISABLED:
            with self._create_connection() as conn:
                self._prepare_connection(conn)
                yield conn
            return
        with self.acquire_interactive() as conn:
            yield conn

    def find_exact_memory(self, data: dict[str, Any]) -> int | None:
        if exact.bypass(data):
            return None
        with self.acquire_interactive() as conn:
            return exact.find_on(conn, data, False)

    def insert_memory_exact(self, data: dict[str, Any]) -> tuple[int, bool]:
        if exact.bypass(data):
            return self.insert_memory(data), True
        with self._exact_connection() as conn, conn.transaction():
            conn.execute(_LOCK, (data["content"],))
            existing = exact.find_on(conn, data, False)
            if existing is not None:
                return existing, False
            return self._insert_memory_on(conn, data), True

    def collapse_exact_replays(self) -> dict[str, int]:
        with self._exact_connection() as conn:
            candidates = conn.execute(exact.candidates_sql(False)).fetchall()
            count = 0
            for candidate in candidates:
                with conn.transaction():
                    row = conn.execute(
                        "SELECT * FROM memories WHERE id = %s", (candidate["id"],)
                    ).fetchone()
                    if row is None:
                        continue
                    lock = conn.execute(_TRY_LOCK, (row["content"],)).fetchone()
                    if not lock["acquired"]:
                        raise RuntimeError("exact replay consolidation group is busy")
                    count += exact.collapse_group(conn, dict(row), False)
        return {"superseded_total": count}
