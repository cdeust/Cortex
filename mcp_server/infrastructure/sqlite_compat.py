"""SQLite <-> psycopg compatibility wrapper.

Translates PostgreSQL SQL conventions to SQLite equivalents so that
handler code using store._conn.execute() with psycopg-style SQL works
unchanged on the SQLite fallback backend.

Translations:
  - %s -> ? (parameter placeholders)
  - ::jsonb, ::TEXT, ::REAL, ::INT -> stripped (type casts)
  - SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
  - TIMESTAMPTZ -> TEXT
  - DEFAULT NOW() -> DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
  - ON CONFLICT ... DO UPDATE SET -> preserved (SQLite 3.24+)
  - RETURNING id -> stripped (use lastrowid instead)
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any


def _translate_sql(sql: str) -> str:
    """Translate psycopg-style SQL to SQLite-compatible SQL."""
    # Parameter placeholders: %s -> ?
    out = sql.replace("%s", "?")

    # Strip PostgreSQL type casts: ::jsonb, ::TEXT, ::REAL, etc.
    out = re.sub(r"::\w+", "", out)

    # SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
    out = re.sub(
        r"\bSERIAL\s+PRIMARY\s+KEY\b",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        out,
        flags=re.IGNORECASE,
    )

    # TIMESTAMPTZ -> TEXT
    out = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", out, flags=re.IGNORECASE)

    # DEFAULT NOW() -> DEFAULT (strftime(...))
    out = re.sub(
        r"\bDEFAULT\s+NOW\(\)",
        "DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        out,
        flags=re.IGNORECASE,
    )

    # Standalone NOW() in VALUES -> strftime(...)
    out = re.sub(
        r"\bNOW\(\)",
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
        out,
        flags=re.IGNORECASE,
    )

    # RETURNING ... -> stripped (not supported in older SQLite)
    out = re.sub(r"\bRETURNING\s+\w+\b", "", out, flags=re.IGNORECASE)

    return out


class _CompatCursor:
    """Wraps a sqlite3.Cursor to mimic psycopg result access."""

    def __init__(
        self, cursor: sqlite3.Cursor, lastrowid: int,
        *, had_returning: bool = False,
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


class PsycopgCompatConnection:
    """Wraps a sqlite3.Connection to accept psycopg-style SQL.

    Handlers that use store._conn.execute("... %s ...", (val,))
    will work transparently with this wrapper.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._real = conn

    def execute(
        self, sql: str, params: Any = None,
    ) -> _CompatCursor:
        """Execute with automatic SQL translation."""
        had_returning = bool(
            re.search(r"\bRETURNING\s+\w+\b", sql, re.IGNORECASE)
        )
        translated = _translate_sql(sql)
        if params:
            cur = self._real.execute(translated, params)
        else:
            cur = self._real.execute(translated)
        return _CompatCursor(
            cur, cur.lastrowid, had_returning=had_returning,
        )

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
