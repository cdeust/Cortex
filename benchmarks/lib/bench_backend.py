"""Storage-backend selection for BenchmarkDB.

PostgreSQL stays the default. SQLite is opt-in (``backend="sqlite"`` or
``CORTEX_BENCH_BACKEND=sqlite``) and uses a throwaway database file that is
removed when the store is released. Only the store lifecycle differs; ingestion
and recall run the same production functions on both backends.

source: docs/agent-guidance.md (benchmarks are passthrough to production)
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

BACKEND_ENV = "CORTEX_BENCH_BACKEND"  # source: this module, opt-in switch
BACKENDS = ("postgresql", "sqlite")  # source: PgMemoryStore, SqliteMemoryStore


def resolve_backend(explicit: str | None) -> str:
    name = (explicit or os.environ.get(BACKEND_ENV) or "postgresql").lower()
    if name not in BACKENDS:
        raise ValueError(
            f"unknown benchmark backend {name!r}; expected one of {BACKENDS}"
        )
    return name


class SqliteBench:
    """A throwaway SqliteMemoryStore in its own temporary directory."""

    def __init__(self, embedding_dim: int) -> None:
        from mcp_server.infrastructure.sqlite_store import (  # noqa: PLC0415 — deferred: keeps the PostgreSQL default path free of the sqlite-vec extra
            SqliteMemoryStore,
        )

        self.directory = tempfile.mkdtemp(prefix="cortex-bench-sqlite-")
        self.store: Any = SqliteMemoryStore(
            os.path.join(self.directory, "bench.db"), embedding_dim=embedding_dim
        )
        if not self.store._has_vec:
            self.release()
            raise RuntimeError(
                "SQLite benchmark backend needs the sqlite-vec extension "
                "(pip install 'neuro-cortex-memory[sqlite]'); without it the "
                "vector signal is absent and the result would not measure "
                "the default backend."
            )

    def delete(self, memory_ids: list[int]) -> None:
        for memory_id in memory_ids:
            self.store.delete_memory(memory_id)

    def release(self) -> None:
        store = getattr(self, "store", None)
        if store is not None:
            store.close()
            self.store = None
        shutil.rmtree(self.directory, ignore_errors=True)
