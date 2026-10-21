"""A store that runs ``store.call`` operations on a given (fake) connection.

Hooks reach the database only through ``store.call(op, ...)`` (ADR-1112);
the hook tests that used to hand the hook a fake psycopg connection now hand
it this store wrapped around the same fake connection, so the operations'
SQL still runs against the fake exactly as before.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

from typing import Any


class ConnStore:
    """``call`` runs ``fn(conn, *args, **kwargs)``, as the in-process store does."""

    def __init__(self, conn: Any, backend: str = "postgresql") -> None:
        self.conn = conn
        self.backend = backend

    def call(
        self, fn: Any, *args: Any, pool: str = "interactive", **kwargs: Any
    ) -> Any:
        return fn(self.conn, *args, **kwargs)


class FailingStore:
    """A store whose every operation raises ``error``."""

    backend = "postgresql"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        raise self.error
