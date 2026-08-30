"""Request-scoped finalization for exact native SQLite handles."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol

logger = logging.getLogger(__name__)


class UncommittedSqliteTransactionError(RuntimeError):
    """A successful request tried to return with uncommitted SQLite work."""


class NestedSqliteRequestScopeError(RuntimeError):
    """A handler attempted to start a second request transaction boundary."""


class SqliteRequestRegistry(Protocol):
    """Registry operations needed to finalize one request's native handles."""

    def rollback_request_connection(self, connection: sqlite3.Connection) -> bool: ...

    def release_request_connection(self, connection: sqlite3.Connection) -> bool: ...


_RequestEntry = tuple[SqliteRequestRegistry, sqlite3.Connection]


class _RequestConnections:
    """Thread-safe identity set shared through copied asyncio contexts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[int, _RequestEntry] = {}

    def add(
        self, registry: SqliteRequestRegistry, connection: sqlite3.Connection
    ) -> None:
        with self._lock:
            self._entries.setdefault(id(connection), (registry, connection))

    def snapshot(self) -> tuple[_RequestEntry, ...]:
        with self._lock:
            return tuple(self._entries.values())


_request_connections: ContextVar[_RequestConnections | None] = ContextVar(
    "sqlite_request_connections", default=None
)


@contextmanager
def sqlite_request_scope() -> Iterator[None]:
    """Finalize every SQLite transaction touched by one handler request."""
    existing = _request_connections.get()
    if existing is not None:
        raise NestedSqliteRequestScopeError(
            "nested handler transaction scopes are unsupported"
        )
    connections = _RequestConnections()
    token = _request_connections.set(connections)
    try:
        yield
    except BaseException:
        _finalize_request_connections(connections, preserve_original=True)
        raise
    else:
        dirty = _finalize_request_connections(connections, preserve_original=False)
        if dirty:
            raise UncommittedSqliteTransactionError(
                f"request left {dirty} uncommitted SQLite transaction(s)"
            )
    finally:
        _request_connections.reset(token)


def register_request_connection(
    registry: SqliteRequestRegistry, connection: sqlite3.Connection
) -> None:
    """Record the exact handle used in the propagated request context."""
    connections = _request_connections.get()
    if connections is not None:
        connections.add(registry, connection)


def _rollback_connections(
    connections: tuple[_RequestEntry, ...],
    *,
    preserve_original: bool,
) -> int:
    dirty = 0
    first_error: Exception | None = None
    for registry, connection in connections:
        try:
            dirty += int(registry.rollback_request_connection(connection))
        except Exception as exc:
            first_error = first_error or exc
            logger.exception("SQLite request rollback failed at handler boundary")
    if first_error is not None and not preserve_original:
        raise first_error
    return dirty


def _finalize_request_connections(
    connections: _RequestConnections,
    *,
    preserve_original: bool,
) -> int:
    snapshot = connections.snapshot()
    try:
        return _rollback_connections(snapshot, preserve_original=preserve_original)
    finally:
        for registry, connection in snapshot:
            registry.release_request_connection(connection)
