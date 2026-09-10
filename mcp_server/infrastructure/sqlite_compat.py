"""source: ADR-0599"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Protocol

from mcp_server.infrastructure.sqlite_sql_translate import (
    _returning_was_stripped,
    _translate_sql,
)


def _adapt_datetime_iso(value: datetime) -> str:
    """Explicit `sqlite3.register_adapter` callback for `datetime.datetime`.

    Precondition: `value` is a `datetime.datetime` instance — sqlite3 only
        invokes a registered adapter with instances of the exact type it was
        registered for. Postcondition: returns `value.isoformat()` — "T"-separated
        ISO-8601,
        identical to `sqlite_store._now_iso()` and every other datetime write
        path in this codebase, so a datetime-bearing column has one wire format
        regardless of whether the caller passed an ISO string directly or (as
        `cascade.py::_update_stage_entered` does) a raw `datetime` object as a
        bound parameter — confirmed the sole such call site in this codebase by
        an instrumented full-suite run .

    source: ADR-0599"""
    return value.isoformat()


# source: ADR-0599
sqlite3.register_adapter(datetime, _adapt_datetime_iso)


class SqliteConnectionLike(Protocol):
    """Native or thread-local connection surface used by the SQL adapter."""

    row_factory: Any

    def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor: ...

    def executemany(self, sql: str, parameters: Any, /) -> sqlite3.Cursor: ...

    def cursor(self, /) -> sqlite3.Cursor: ...

    def executescript(self, sql: str, /) -> Any: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...

    def enable_load_extension(self, enabled: bool) -> None: ...


class _CompatCursor:
    """Wraps a sqlite3.Cursor to mimic psycopg result access."""

    def __init__(
        self,
        cursor: sqlite3.Cursor,
        lastrowid: int | None,
        *,
        had_returning: bool = False,
    ) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount
        self._had_returning = had_returning

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            # Only fake {"id": lastrowid} when RETURNING was stripped
            if self._had_returning and self.lastrowid:
                return {"id": self.lastrowid}
            return None
        return dict(row) if hasattr(row, "keys") else row

    def fetchall(self) -> list:
        rows = self._cursor.fetchall()
        return [dict(r) if hasattr(r, "keys") else r for r in rows]


class _CompatExecutingCursor:
    """A psycopg-style cursor: `with conn.cursor() as cur: cur.execute(...)`.

    source: ADR-0599"""

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor
        self.lastrowid: int | None = None
        self.rowcount: int = -1
        self._had_returning = False

    def __enter__(self) -> "_CompatExecutingCursor":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        self.close()
        return False

    def execute(self, sql: str, params: Any = None) -> "_CompatExecutingCursor":
        self._had_returning = _returning_was_stripped(sql)
        translated = _translate_sql(sql)
        if params:
            self._cursor.execute(translated, params)
        else:
            self._cursor.execute(translated)
        self.lastrowid = self._cursor.lastrowid
        self.rowcount = self._cursor.rowcount
        return self

    def executemany(self, sql: str, params_seq: Any) -> "_CompatExecutingCursor":
        """psycopg-parity executemany with SQL translation.

        source: ADR-0599"""
        translated = _translate_sql(sql)
        self._had_returning = False
        self._cursor.executemany(translated, params_seq)
        self.lastrowid = self._cursor.lastrowid
        self.rowcount = self._cursor.rowcount
        return self

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            # source: ADR-0599
            if self._had_returning and self.lastrowid:
                return {"id": self.lastrowid}
            return None
        return dict(row) if hasattr(row, "keys") else row

    def fetchall(self) -> list:
        return [dict(r) if hasattr(r, "keys") else r for r in self._cursor.fetchall()]

    def close(self) -> None:
        self._cursor.close()


class PsycopgCompatConnection:
    """Wraps a sqlite3.Connection to accept psycopg-style SQL.

    Handlers that use store._conn.execute("... %s ...", (val,))
    will work transparently with this wrapper.
    """

    def __init__(self, conn: SqliteConnectionLike) -> None:
        self._real = conn

    def execute(
        self,
        sql: str,
        params: Any = None,
    ) -> _CompatCursor:
        """Execute with automatic SQL translation."""
        had_returning = _returning_was_stripped(sql)
        translated = _translate_sql(sql)
        if params:
            cur = self._real.execute(translated, params)
        else:
            cur = self._real.execute(translated)
        return _CompatCursor(
            cur,
            cur.lastrowid,
            had_returning=had_returning,
        )

    def cursor(self, row_factory: Any = None) -> _CompatExecutingCursor:
        """Return a psycopg-style cursor (context manager, translating).

        source: ADR-0599"""
        return _CompatExecutingCursor(self._real.cursor())

    def executescript(self, sql: str) -> None:
        """Execute multiple statements (DDL). No param translation."""
        self._real.executescript(sql)

    def commit(self) -> None:
        self._real.commit()

    def rollback(self) -> None:
        self._real.rollback()

    def close(self) -> None:
        self._real.close()

    @property
    def row_factory(self) -> Any:
        return self._real.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._real.row_factory = value

    def enable_load_extension(self, enabled: bool) -> None:
        self._real.enable_load_extension(enabled)
