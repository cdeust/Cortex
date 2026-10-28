"""psycopg cursor that routes write parameters through the redaction gate.

``PgSchemaMixin`` installs it as the ``cursor_factory`` of the persistent
connection and of every pooled connection (``_prepare_connection``, the pools'
``configure`` callback). ``Connection.execute`` and ``Connection.cursor()``
both build their cursor from ``cursor_factory``, so every store write, the
wiki writers that receive a caller's ``conn``, handlers that borrow a pool
connection, ``executemany`` sinks and the two COPY sinks are covered by one
class. Server-side (named) cursors use ``server_cursor_factory``; Cortex only
reads through them.

source: ADR-1110"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import DictRow
from psycopg.types.json import Json, Jsonb

from mcp_server.shared.redaction_gate import is_write_statement, redact_value


def _statement_text(cursor: psycopg.Cursor[Any], query: Any) -> str:
    if isinstance(query, str):
        return query
    if isinstance(query, bytes):
        return query.decode("utf-8", "replace")
    if isinstance(query, sql.Composable):
        return query.as_string(cursor.connection)
    return str(query)


def _gate(value: Any) -> Any:
    if isinstance(value, (Json, Jsonb)):
        return type(value)(_gate(value.obj), value.dumps)
    if isinstance(value, dict):
        return {k: _gate(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_gate(v) for v in value)
    return redact_value(value)


class _GatedCopy:
    """COPY proxy: rows are redacted; raw ``write`` cannot be gated, so refused."""

    def __init__(self, copy: psycopg.Copy) -> None:
        self._copy = copy

    def write_row(self, row: Any) -> None:
        self._copy.write_row(_gate(row))

    def write(self, buffer: Any) -> None:
        raise TypeError("raw COPY data bypasses the redaction gate; use write_row")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._copy, name)


class GatedCursor(psycopg.Cursor[DictRow]):
    """A cursor whose write statements bind redacted parameters."""

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> "GatedCursor":
        if params is not None and is_write_statement(_statement_text(self, query)):
            params = _gate(params)
        return super().execute(query, params, **kwargs)

    def executemany(self, query: Any, params_seq: Iterable[Any], **kwargs: Any) -> None:
        if is_write_statement(_statement_text(self, query)):
            params_seq = [_gate(p) for p in params_seq]
        return super().executemany(query, params_seq, **kwargs)

    @contextmanager
    def copy(self, statement: Any, params: Any = None, **kwargs: Any) -> Iterator[Any]:
        with super().copy(statement, params, **kwargs) as copy:
            yield _GatedCopy(copy)


def install(conn: psycopg.Connection[Any]) -> None:
    """Make ``conn`` hand out only gated cursors."""
    conn.cursor_factory = GatedCursor
