"""Shared base for pooled batch sinks — one borrowed connection per worker.

A ``BatchSink`` adapter holds one pooled PostgreSQL connection for the lifetime
of its pipeline worker (sharing a connection across threads is unsafe). This
base owns the lazy borrow / release and a per-connection setup hook; concrete
sinks (Copy, ExecuteMany, StagingResolve) implement ``write_batch``.

Pure infrastructure — no core imports.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Callable, Sequence

if TYPE_CHECKING:
    import psycopg

# source: ADR-0591
ConnectAcquire = Callable[[], "AbstractContextManager[psycopg.Connection]"]
RowAdapter = Callable[[Any], Sequence[Any]]


class PooledConnectionSink:
    """Owns one borrowed connection; subclasses implement ``write_batch``."""

    def __init__(self, acquire: ConnectAcquire, row_adapter: RowAdapter | None = None):
        self._acquire = acquire
        self._row_adapter: RowAdapter = row_adapter or (lambda r: r)
        self._cm: AbstractContextManager[psycopg.Connection] | None = None
        self._conn: psycopg.Connection | None = None

    def _on_connect(self, conn: psycopg.Connection) -> None:
        """Hook run once when the connection is first borrowed (default no-op).

        Overridden by sinks that need per-session setup (e.g. a temp staging
        table declared ``ON COMMIT DELETE ROWS``).
        """

    def _ensure_conn(self) -> psycopg.Connection:
        if self._conn is None:
            self._cm = self._acquire()
            self._conn = self._cm.__enter__()
            self._on_connect(self._conn)
        return self._conn

    def write_batch(self, batch: list[Any]) -> int:  # pragma: no cover - abstract
        raise NotImplementedError

    def close(self) -> None:
        """Return the connection to the pool. Idempotent."""
        if self._cm is not None:
            self._cm.__exit__(None, None, None)
            self._cm = None
            self._conn = None
