"""A live SQLite store is copied as of one instant (issue #731, slice 3)."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
import threading
from contextlib import closing

import pytest

from mcp_server.infrastructure.sqlite_snapshot import SnapshotError, snapshot_sqlite


def _wal_store(path):
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE pairs (batch INTEGER, side INTEGER)")
    connection.commit()
    return connection


def _count(path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT count(*) FROM pairs").fetchone()[0]


def test_rows_committed_only_in_the_wal_are_in_the_copy(tmp_path):
    source, target = tmp_path / "memory.db", tmp_path / "copy" / "memory.db"
    target.parent.mkdir()
    writer = _wal_store(source)
    writer.executemany("INSERT INTO pairs VALUES (?, 0)", [(i,) for i in range(500)])
    writer.commit()
    assert (tmp_path / "memory.db-wal").stat().st_size > 0

    snapshot_sqlite(source, target)
    writer.close()

    assert _count(target) == 500
    assert sorted(p.name for p in target.parent.iterdir()) == ["memory.db"]
    with closing(sqlite3.connect(target)) as copy:
        assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_a_copy_taken_under_concurrent_writes_holds_whole_transactions(tmp_path):
    source = tmp_path / "memory.db"
    writer = _wal_store(source)
    stop = threading.Event()

    def write_pairs() -> None:
        batch = 0
        while not stop.is_set():
            rows = [(batch, 0), (batch, 1)]
            writer.executemany("INSERT INTO pairs VALUES (?, ?)", rows)
            writer.commit()
            batch += 1

    thread = threading.Thread(target=write_pairs)
    thread.start()
    try:
        counts = []
        for index in range(20):
            target = tmp_path / f"copy-{index}.db"
            snapshot_sqlite(source, target)
            counts.append(_count(target))
    finally:
        stop.set()
        thread.join()
        writer.close()
    assert all(count % 2 == 0 for count in counts), counts
    assert counts[-1] > 0


def test_a_missing_source_is_refused_and_not_created(tmp_path):
    source = tmp_path / "memory.db"
    with pytest.raises(SnapshotError, match="not a regular SQLite file"):
        snapshot_sqlite(source, tmp_path / "copy.db")
    assert not source.exists()


@pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)
def test_a_linked_source_is_refused(tmp_path):
    real = tmp_path / "real.db"
    _wal_store(real).close()
    (tmp_path / "memory.db").symlink_to(real)
    with pytest.raises(SnapshotError, match="not a regular SQLite file"):
        snapshot_sqlite(tmp_path / "memory.db", tmp_path / "copy.db")


def test_an_existing_target_is_never_overwritten(tmp_path):
    source, target = tmp_path / "memory.db", tmp_path / "copy.db"
    _wal_store(source).close()
    target.write_bytes(b"keep")
    with pytest.raises(SnapshotError, match="never overwrites"):
        snapshot_sqlite(source, target)
    assert target.read_bytes() == b"keep"


def test_a_corrupt_source_is_refused(tmp_path):
    source = tmp_path / "memory.db"
    source.write_bytes(b"not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        snapshot_sqlite(source, tmp_path / "copy.db")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_copy_is_owner_only_whatever_the_umask(tmp_path):
    source, target = tmp_path / "memory.db", tmp_path / "copy.db"
    _wal_store(source).close()
    previous = os.umask(0o022)
    try:
        snapshot_sqlite(source, target)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
