"""Tests for infrastructure/batch_sinks — COPY and executemany adapters.

Contract under test (module docstring): one batch in, durably committed,
released — atomic per batch via ``conn.transaction()``. The connection
is injected through the ``ConnectAcquire`` seam, so these tests drive
the sinks with mock connections and assert the observable protocol:
what was written, inside a transaction, on one lazily-borrowed
connection, released by ``close()``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mcp_server.infrastructure.batch_sinks import (
    CopyBatchSink,
    ExecuteManyBatchSink,
)


def _acquire_returning(conn):
    """A ConnectAcquire whose context manager yields ``conn``."""
    cm = MagicMock()
    cm.__enter__.return_value = conn
    return MagicMock(return_value=cm), cm


# ── CopyBatchSink ─────────────────────────────────────────────────────


def test_copy_sink_empty_batch_writes_nothing_and_borrows_no_connection():
    acquire, _cm = _acquire_returning(MagicMock())
    sink = CopyBatchSink(acquire, copy_sql="COPY t FROM STDIN")

    assert sink.write_batch([]) == 0
    acquire.assert_not_called()


def test_copy_sink_writes_each_row_inside_a_transaction():
    conn = MagicMock()
    acquire, _cm = _acquire_returning(conn)
    sink = CopyBatchSink(
        acquire, copy_sql="COPY t FROM STDIN", row_adapter=lambda r: (r, r * 2)
    )

    written = sink.write_batch([1, 2, 3])

    assert written == 3
    conn.transaction.assert_called_once()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.copy.assert_called_once_with("COPY t FROM STDIN")
    cp = cur.copy.return_value.__enter__.return_value
    assert [c.args[0] for c in cp.write_row.call_args_list] == [
        (1, 2),
        (2, 4),
        (3, 6),
    ], "the row adapter shapes every written row"


def test_copy_sink_reuses_one_borrowed_connection_across_batches():
    conn = MagicMock()
    acquire, _cm = _acquire_returning(conn)
    sink = CopyBatchSink(acquire, copy_sql="COPY t FROM STDIN")

    sink.write_batch([1])
    sink.write_batch([2])

    acquire.assert_called_once(), "lazy borrow happens exactly once"


def test_copy_sink_close_releases_the_connection_and_is_idempotent():
    conn = MagicMock()
    acquire, cm = _acquire_returning(conn)
    sink = CopyBatchSink(acquire, copy_sql="COPY t FROM STDIN")
    sink.write_batch([1])

    sink.close()
    sink.close()

    cm.__exit__.assert_called_once_with(None, None, None)


# ── ExecuteManyBatchSink ──────────────────────────────────────────────


def test_executemany_sink_empty_batch_writes_nothing():
    acquire, _cm = _acquire_returning(MagicMock())
    sink = ExecuteManyBatchSink(acquire, insert_sql="INSERT ...")

    assert sink.write_batch([]) == 0
    acquire.assert_not_called()


def test_executemany_sink_passes_adapted_params_and_reports_rowcount():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.rowcount = 2
    acquire, _cm = _acquire_returning(conn)
    sink = ExecuteManyBatchSink(
        acquire,
        insert_sql="INSERT ... ON CONFLICT DO NOTHING",
        row_adapter=lambda r: (r,),
    )

    written = sink.write_batch(["a", "b"])

    assert written == 2
    conn.transaction.assert_called_once()
    cur.executemany.assert_called_once_with(
        "INSERT ... ON CONFLICT DO NOTHING", [("a",), ("b",)]
    )


def test_executemany_sink_missing_rowcount_falls_back_to_batch_length():
    # psycopg reports rowcount -1 when the server does not send a count;
    # the sink's contract is "assume the whole batch landed" rather than
    # reporting a negative write.
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.rowcount = -1
    acquire, _cm = _acquire_returning(conn)
    sink = ExecuteManyBatchSink(acquire, insert_sql="INSERT ...")

    assert sink.write_batch([1, 2, 3]) == 3
