"""SQL compatibility layer for PostgreSQL and SQLite.

Provides helpers to execute raw SQL on either backend without
handlers needing to know which database is active.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def is_sqlite(conn: Any) -> bool:
    """Check if the connection is SQLite."""
    return isinstance(conn, sqlite3.Connection)


def execute(conn: Any, sql: str, params: tuple = ()) -> Any:
    """Execute SQL on either PostgreSQL or SQLite.

    Translates %s placeholders to ? for SQLite.
    Translates ::jsonb casts to empty string for SQLite.
    """
    if is_sqlite(conn):
        sql = _pg_to_sqlite(sql)
    return conn.execute(sql, params)


def fetchone(conn: Any, sql: str, params: tuple = ()) -> dict | None:
    """Execute and fetch one row."""
    cur = execute(conn, sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return dict(row) if is_sqlite(conn) else (dict(row) if hasattr(row, 'keys') else row)


def fetchall(conn: Any, sql: str, params: tuple = ()) -> list:
    """Execute and fetch all rows."""
    cur = execute(conn, sql, params)
    rows = cur.fetchall()
    if is_sqlite(conn):
        return [dict(r) for r in rows]
    return [dict(r) if hasattr(r, 'keys') else r for r in rows]


def commit(conn: Any) -> None:
    """Commit the connection."""
    conn.commit()


def _pg_to_sqlite(sql: str) -> str:
    """Translate PostgreSQL SQL to SQLite-compatible SQL."""
    # Replace %s with ?
    sql = sql.replace("%s", "?")
    # Remove ::jsonb casts
    sql = sql.replace("::jsonb", "")
    # Replace NOW() with datetime('now')
    sql = sql.replace("NOW()", "datetime('now')")
    # Replace LEAST with MIN
    sql = sql.replace("LEAST(", "MIN(")
    return sql
