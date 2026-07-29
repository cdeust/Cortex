"""SQLite <-> psycopg compatibility wrapper.

Wraps a sqlite3 connection/cursor so handler code written against psycopg's
API (``conn.execute("... %s ...", params)``, ``with conn.cursor() as cur``)
runs unmodified on the SQLite fallback backend. SQL-dialect rewriting
(``%s`` -> ``?``, ``TIMESTAMPTZ`` -> ``TEXT``, etc.) lives in
``sqlite_sql_translate.py`` (split out in issue #260 to keep this file
under the project's 300-line cap); this module owns parameter adaptation
and the cursor/connection shape.

Datetime wire format (issue #260): a bound `datetime.datetime` parameter is
serialized via `_adapt_datetime_iso` below — plain `.isoformat()`, the same
"T"-separated spelling `sqlite_store._now_iso()` and every other datetime
write path in this codebase already produce. This replaces reliance on the
stdlib's *implicit* default adapter (deprecated as of Python 3.12; see
`_adapt_datetime_iso`'s docstring for the exact spelling it used to produce
and why old rows keep reading correctly with no migration).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any

from mcp_server.infrastructure.sqlite_sql_translate import (
    _returning_was_stripped,
    _translate_sql,
)


def _adapt_datetime_iso(value: datetime) -> str:
    """Explicit `sqlite3.register_adapter` callback for `datetime.datetime`.

    Precondition: `value` is a `datetime.datetime` instance — sqlite3 only
    invokes a registered adapter with instances of the exact type it was
    registered for.
    Postcondition: returns `value.isoformat()` — "T"-separated ISO-8601,
    identical to `sqlite_store._now_iso()` and every other datetime write
    path in this codebase, so a datetime-bearing column has one wire format
    regardless of whether the caller passed an ISO string directly or (as
    `cascade.py::_update_stage_entered` does) a raw `datetime` object as a
    bound parameter — confirmed the sole such call site in this codebase by
    an instrumented full-suite run (issue #260).

    This supersedes the stdlib's *implicit* default adapter, deprecated as
    of Python 3.12: that fallback produced `value.isoformat(" ")` (a space
    separator) instead of "T". `datetime.fromisoformat()` — the read path
    used by every reader of a datetime-bearing column here (`decay_cycle.py`,
    `consolidation_engine.py`, `cascade.py`) — parses both spellings to an
    identical `datetime` object (verified empirically, CPython 3.12.12:
    `fromisoformat("2026-07-29 12:34:56.789012+00:00") ==
    fromisoformat("2026-07-29T12:34:56.789012+00:00")`), so rows already on
    disk in the old spelling keep reading correctly — no migration needed.
    """
    return value.isoformat()


# Registered once at import time (idempotent — sqlite3 stores adapters in a
# type-keyed dict, so re-import / re-registration just overwrites the same
# entry). Must happen before any `datetime` is bound as a parameter through
# this module's execute()/executemany() paths; every construction site of
# `PsycopgCompatConnection` imports this module first (there is no other way
# to obtain the class), so that ordering is guaranteed.
sqlite3.register_adapter(datetime, _adapt_datetime_iso)


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

    Distinct from _CompatCursor, which wraps a statement the connection has
    ALREADY executed. This one owns a raw cursor and translates each SQL
    string on the way in, so the wiki handlers — written against psycopg and
    shared verbatim with the PostgreSQL backend — run unmodified on SQLite.
    """

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

        Shared query modules (e.g. ``pg_store_wiki_sources.upsert_page_sources``)
        batch their inserts through ``cur.executemany``; without this method the
        whole call chain raised ``AttributeError`` on the SQLite backend — the
        same silent-degradation class as issue #206. RETURNING is not supported
        here (psycopg's ``executemany`` does not return rows either).
        """
        translated = _translate_sql(sql)
        self._had_returning = False
        self._cursor.executemany(translated, params_seq)
        self.lastrowid = self._cursor.lastrowid
        self.rowcount = self._cursor.rowcount
        return self

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            # _translate_sql strips RETURNING, so an INSERT ... RETURNING id
            # yields no row here. pg_store_wiki_common._returning_id RAISES
            # on None, so the id must be synthesised from lastrowid or every
            # bulk insert in the wiki pipeline fails.
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

    def __init__(self, conn: sqlite3.Connection) -> None:
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

        Its absence is the root cause of issue #206: the wiki pipeline's
        seven handlers all reach for `conn.cursor()`, so every stage failed
        with AttributeError on SQLite and the caller recorded it as a string.

        `row_factory` is accepted for signature parity with psycopg's
        `conn.cursor(row_factory=DICT_ROW)` — 29 shared call sites use it —
        and is then ignored: this cursor already returns dict rows
        unconditionally, which is exactly what `dict_row` asks for. psycopg's
        other keyword, `name=` (server-side cursor), is deliberately NOT
        accepted; its single call site lives in the PgMemoryStore-only
        pg_store_queries mixin and cannot reach this class.
        """
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
