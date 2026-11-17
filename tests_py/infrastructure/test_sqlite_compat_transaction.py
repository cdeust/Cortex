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


def _conn(raw: sqlite3.Connection | None = None) -> PsycopgCompatConnection:
    conn = PsycopgCompatConnection(raw or sqlite3.connect(":memory:"))
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


def test_a_refused_final_release_is_undone_and_leaves_no_open_transaction():
    # source: PR #1083 review — the final RELEASE sat outside the undo path.
    raw = sqlite3.connect(":memory:")
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("CREATE TABLE p (id INTEGER PRIMARY KEY)")
    raw.execute(
        "CREATE TABLE c (pid INTEGER REFERENCES p(id) DEFERRABLE INITIALLY DEFERRED)"
    )
    conn = PsycopgCompatConnection(raw)
    with pytest.raises(sqlite3.IntegrityError), conn.transaction():
        conn.execute("INSERT INTO c VALUES (%s)", (99,))  # checked at RELEASE
    assert raw.in_transaction is False
    assert raw.execute("SELECT count(*) FROM c").fetchone()[0] == 0


def test_a_failed_rollback_does_not_hide_the_block_exception():
    # source: PR #1083 review — ROLLBACK TO failing replaced the real error.
    conn = _conn()
    with pytest.raises(RuntimeError, match="interrupted") as caught:
        with conn.transaction():
            conn.execute("RELEASE SAVEPOINT cortex_tx")  # the undo now fails
            raise RuntimeError("interrupted")
    assert any("savepoint rollback also failed" in n for n in caught.value.__notes__)


def test_a_failed_block_inside_an_outer_unit_leaves_that_unit_open():
    # source: PR #1087 review — no test pinned the outer unit staying open.
    raw = sqlite3.connect(":memory:")
    conn = _conn(raw)
    conn.execute("INSERT INTO t VALUES (%s)", (7,))
    with pytest.raises(RuntimeError), conn.transaction():
        conn.execute("INSERT INTO t VALUES (%s)", (8,))
        raise RuntimeError("interrupted")
    assert raw.in_transaction is True
    assert _values(conn) == [7]


def test_a_failed_undo_can_leave_the_block_writes_pending():
    # source: PR #1087 review — the pending state after a failed undo was untested.
    raw = sqlite3.connect(":memory:")
    conn = _conn(raw)
    conn.execute("INSERT INTO t VALUES (%s)", (7,))
    with pytest.raises(RuntimeError, match="interrupted"), conn.transaction():
        conn.execute("INSERT INTO t VALUES (%s)", (8,))
        conn.execute("RELEASE SAVEPOINT cortex_tx")  # ROLLBACK TO now fails
        raise RuntimeError("interrupted")
    assert raw.in_transaction is True
    assert _values(conn) == [7, 8]
    conn.commit()
    assert _values(conn) == [7, 8]
