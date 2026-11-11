"""A live SQLite store is copied as of one instant (issue #731, slice 3)."""

from __future__ import annotations

import os
import sqlite3
import stat
import sys
import threading
from contextlib import closing

import pytest

from mcp_server.infrastructure import sqlite_snapshot
from mcp_server.infrastructure.sqlite_snapshot import (
    SnapshotError,
    check_snapshot,
    snapshot_sqlite,
)


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


def test_a_target_whose_directory_is_missing_is_refused(tmp_path):
    source, target = tmp_path / "memory.db", tmp_path / "absent" / "copy.db"
    _wal_store(source).close()
    with pytest.raises(SnapshotError, match=r"absent is not a directory$"):
        snapshot_sqlite(source, target)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0]

    def __iter__(self):
        return iter(self._rows)


class _Copy:
    """A connection whose PRAGMA answers are given: what a damaged copy reports."""

    def __init__(self, journal, integrity):
        self.answers = {
            "PRAGMA journal_mode=DELETE": journal,
            "PRAGMA integrity_check": integrity,
        }

    def execute(self, sql):
        return _Rows(self.answers[sql])


def test_a_copy_that_keeps_its_wal_is_refused():
    with pytest.raises(SnapshotError, match=r"^the copy kept journal_mode=wal$"):
        sqlite_snapshot._seal(_Copy([("wal",)], [("ok",)]))


def test_a_copy_that_fails_integrity_check_is_refused_with_every_finding():
    findings = [(f"row {n} missing from index",) for n in range(5)]
    message = "; ".join(f[0] for f in findings)
    with pytest.raises(SnapshotError) as refused:
        sqlite_snapshot._seal(_Copy([("delete",)], findings))
    assert str(refused.value) == f"the copy failed integrity_check: {message}"


def test_the_source_is_opened_read_only_by_an_explicit_uri(tmp_path, monkeypatch):
    """``mode=ro`` is a URI parameter: without ``uri=True`` a Python whose SQLite
    is built without SQLITE_USE_URI would open (or create) a file of that name."""
    source = tmp_path / "memory.db"
    _wal_store(source).close()
    opened = []

    def spy(target, **kwargs):
        opened.append((target, kwargs))
        return sqlite3.connect(":memory:")

    monkeypatch.setattr(sqlite_snapshot, "sqlite_connect", spy)
    sqlite_snapshot._open_source(source).close()
    assert opened == [(f"{source.resolve().as_uri()}?mode=ro", {"uri": True})]


def test_an_intact_copy_passes_the_check_and_nothing_is_written_beside_it(tmp_path):
    source, copy = tmp_path / "memory.db", tmp_path / "copy" / "memory.db"
    copy.parent.mkdir()
    _wal_store(source).close()
    snapshot_sqlite(source, copy)
    before = copy.read_bytes()

    check_snapshot(copy)

    assert sorted(p.name for p in copy.parent.iterdir()) == ["memory.db"]
    assert copy.read_bytes() == before


def test_a_file_sqlite_cannot_read_fails_the_check(tmp_path):
    copy = tmp_path / "memory.db"
    copy.write_bytes(b"not a database" * 100)
    with pytest.raises(SnapshotError) as refused:
        check_snapshot(copy)
    assert str(refused.value) == (
        f"{copy} is not a readable SQLite database: file is not a database"
    )
    assert isinstance(refused.value.__cause__, sqlite3.DatabaseError)


def test_a_missing_file_fails_the_check_and_is_not_created(tmp_path):
    copy = tmp_path / "memory.db"
    with pytest.raises(SnapshotError, match="is not a readable SQLite database"):
        check_snapshot(copy)
    assert not copy.exists()


class _ClosableCopy(_Copy):
    def close(self):
        pass


def test_the_check_reads_the_copy_immutable_and_reports_every_finding(
    tmp_path, monkeypatch
):
    copy = tmp_path / "memory.db"
    findings = [(f"row {n} missing from index",) for n in range(3)]
    opened = []

    def spy(target, **kwargs):
        opened.append((target, kwargs))
        return _ClosableCopy([("delete",)], findings)

    monkeypatch.setattr(sqlite_snapshot, "sqlite_connect", spy)
    with pytest.raises(SnapshotError) as refused:
        check_snapshot(copy)
    message = "; ".join(f[0] for f in findings)
    assert str(refused.value) == f"{copy} failed integrity_check: {message}"
    uri = f"{copy.resolve().as_uri()}?mode=ro&immutable=1"
    assert opened == [(uri, {"uri": True})]
