"""``PsycopgCompatConnection.transaction()``: all of the block or none.

The SQLite adapter mirrors psycopg's ``Connection.transaction()`` so a
handler that needs several writes to land together (``wiki_write``'s page
row and citations, issue #715 slice 3) states it once for both backends.

source: issue #715 (slice 3); https://sqlite.org/lang_savepoint.html
"""

from __future__ import annotations

import sqlite3

import pytest

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


def _conn() -> PsycopgCompatConnection:
    conn = PsycopgCompatConnection(sqlite3.connect(":memory:"))
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.commit()
    return conn


def _values(conn: PsycopgCompatConnection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY v").fetchall()]


def test_a_block_that_ends_normally_is_committed():
    conn = _conn()
    with conn.transaction():
        conn.execute("INSERT INTO t VALUES (%s)", (1,))
        conn.execute("INSERT INTO t VALUES (%s)", (2,))
    conn.rollback()
    assert _values(conn) == [1, 2]


def test_a_block_that_raises_keeps_none_of_its_writes():
    conn = _conn()
    with pytest.raises(RuntimeError), conn.transaction():
        conn.execute("INSERT INTO t VALUES (%s)", (1,))
        raise RuntimeError("interrupted")
    conn.commit()
    assert _values(conn) == []


def test_a_failed_block_leaves_the_outer_pending_writes_untouched():
    conn = _conn()
    conn.execute("INSERT INTO t VALUES (%s)", (7,))
    with pytest.raises(RuntimeError), conn.transaction():
        conn.execute("INSERT INTO t VALUES (%s)", (8,))
        raise RuntimeError("interrupted")
    conn.commit()
    assert _values(conn) == [7]
