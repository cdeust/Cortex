"""Thread-confined SQLite connections behind one stable store facade.

SQLite defines transaction isolation at the connection boundary.  The MCP
server executes synchronous handlers on worker threads, so each execution
thread must own the connection whose commit or rollback ends its transaction.
The handler scope then rolls back unfinished work before a worker is reused.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.sqlite_request_scope import (
    register_request_connection,
)

_VectorLoader = Callable[[sqlite3.Connection], None]
logger = logging.getLogger(__name__)


class SqliteConnectionRegistry:
    """Own request-scoped thread handles plus one store-lifetime anchor."""

    def __init__(self, path: str) -> None:
        self._target, self._uri = _connection_target(path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: list[sqlite3.Connection] = []
        self._anchor_connection: sqlite3.Connection | None = None
        self._vector_loader: _VectorLoader | None = None
        self._invalid_reason: str | None = None
        self._closed = False
        self._anchor_connection = self._open_locked()
        self._local.connection = self._anchor_connection

    def connection(self) -> sqlite3.Connection:
        """Return the connection owned by the calling execution thread."""
        with self._lock:
            if self._closed:
                raise sqlite3.ProgrammingError("SQLite connection registry is closed")
            if self._invalid_reason is not None:
                raise sqlite3.ProgrammingError(self._invalid_reason)
            connection = getattr(self._local, "connection", None)
            if connection not in self._connections:
                connection = self._open_locked()
                if self._anchor_connection is None:
                    self._anchor_connection = connection
                self._local.connection = connection
        register_request_connection(self, connection)
        return connection

    def enable_vector_extension(self, loader: _VectorLoader) -> None:
        """Load an optional extension on present and future connections."""
        with self._lock:
            for connection in self._connections:
                _load_extension(connection, loader)
            self._vector_loader = loader

    def close(self) -> None:
        """Close every worker connection after the store becomes quiescent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            connections = tuple(self._connections)
            self._connections.clear()
            self._anchor_connection = None
            self._local.connection = None
        for connection in connections:
            connection.close()

    def rollback_request_connection(self, connection: sqlite3.Connection) -> bool:
        """Roll back one exact request handle; quarantine it on failure."""
        with self._lock:
            if connection not in self._connections:
                return False
        if not connection.in_transaction:
            return False
        try:
            _rollback_native(connection)
        except Exception:
            self._discard_connection(connection)
            raise
        return True

    def release_request_connection(self, connection: sqlite3.Connection) -> bool:
        """Close a request-owned handle unless it anchors the store lifetime."""
        return self._discard_connection(connection, preserve_anchor=True)

    def _discard_connection(
        self,
        connection: sqlite3.Connection,
        *,
        preserve_anchor: bool = False,
    ) -> bool:
        with self._lock:
            if preserve_anchor and connection is self._anchor_connection:
                return False
            if connection not in self._connections:
                return False
            self._connections.remove(connection)
            if connection is self._anchor_connection:
                self._anchor_connection = None
                if self._uri:
                    self._invalid_reason = (
                        "SQLite in-memory registry invalidated because its "
                        "anchor rollback failed"
                    )
            if getattr(self._local, "connection", None) is connection:
                self._local.connection = None
        try:
            connection.close()
        except sqlite3.Error:
            logger.exception("SQLite connection release or quarantine close failed")
        return True

    def _open_locked(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._target,
            uri=self._uri,
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        try:
            expected_journal_mode = "memory" if self._uri else "wal"
            _configure(
                connection,
                expected_journal_mode=(
                    expected_journal_mode if not self._connections else None
                ),
            )
            if self._vector_loader is not None:
                _load_extension(connection, self._vector_loader)
        except BaseException:
            connection.close()
            raise
        self._connections.append(connection)
        return connection


class ThreadLocalSqliteConnection:
    """Stable connection-shaped proxy resolving the caller's native handle."""

    def __init__(self, registry: SqliteConnectionRegistry) -> None:
        self._registry = registry

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        return self._registry.connection().execute(sql, parameters)

    def executemany(self, sql: str, parameters: Any) -> sqlite3.Cursor:
        return self._registry.connection().executemany(sql, parameters)

    def cursor(self) -> sqlite3.Cursor:
        return self._registry.connection().cursor()

    def executescript(self, sql: str) -> sqlite3.Cursor:
        return self._registry.connection().executescript(sql)

    def commit(self) -> None:
        self._registry.connection().commit()

    def rollback(self) -> None:
        self._registry.connection().rollback()

    def close(self) -> None:
        self._registry.close()

    @property
    def row_factory(self) -> Any:
        return self._registry.connection().row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._registry.connection().row_factory = value

    def enable_load_extension(self, enabled: bool) -> None:
        self._registry.connection().enable_load_extension(enabled)


def _connection_target(path: str) -> tuple[str, bool]:
    if path != ":memory:":
        return str(Path(path).resolve()), False
    name = f"cortex-{uuid.uuid4().hex}"
    return f"file:{name}?mode=memory&cache=shared", True


def _configure(
    connection: sqlite3.Connection, *, expected_journal_mode: str | None
) -> None:
    connection.row_factory = sqlite3.Row
    if expected_journal_mode is not None:
        row = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        actual_mode = str(row[0]).lower()
        if actual_mode != expected_journal_mode:
            logger.warning(
                "SQLite requested WAL but retained journal_mode=%s", actual_mode
            )
    connection.execute("PRAGMA foreign_keys=ON")


def _load_extension(connection: sqlite3.Connection, loader: _VectorLoader) -> None:
    connection.enable_load_extension(True)
    try:
        loader(connection)
    finally:
        connection.enable_load_extension(False)


def _rollback_native(connection: sqlite3.Connection) -> None:
    connection.rollback()
