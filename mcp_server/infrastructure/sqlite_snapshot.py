"""One consistent copy of a live SQLite store (issue #731, slice 3).

``snapshot_sqlite`` copies a database that other connections may be writing by
SQLite's online backup API, in one step: the copy is the database as of one
read transaction, including what is committed only in the ``-wal`` file. A
file copy of ``memory.db`` alone would miss the WAL, and three file copies
(``memory.db``, ``-wal``, ``-shm``) taken one after the other are not one
instant.

The copy is then switched to ``journal_mode=DELETE`` so it is a single
self-contained file (the backup carries the source's WAL header), and checked
with ``PRAGMA integrity_check``. The source is opened read-only, so a missing
source is refused instead of being created empty.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §3, §5;
SQLite online backup API, https://www.sqlite.org/backup.html ("the backup
is ... a snapshot of the source database at the point in time the read
transaction was opened" when done in one sqlite3_backup_step(-1) call).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


class SnapshotError(OSError):
    """A store cannot be copied as one consistent, self-contained file."""


def _open_source(source: Path) -> sqlite3.Connection:
    if not source.is_file() or source.is_symlink():
        raise SnapshotError(f"{source} is not a regular SQLite file")
    return sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)


def _seal(target: sqlite3.Connection, path: Path) -> None:
    """Make the copy one file and refuse it if SQLite does not call it intact."""
    mode = target.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    if mode != "delete":
        raise SnapshotError(f"{path} kept journal_mode={mode}")
    verdict = [row[0] for row in target.execute("PRAGMA integrity_check")]
    if verdict != ["ok"]:
        raise SnapshotError(f"{path} failed integrity_check: {verdict[:3]}")


def snapshot_sqlite(source: Path, target: Path) -> None:
    """Write the database at ``source`` to the new file ``target``, as of one instant.

    ``target`` must not exist; its directory is created.
    """
    if target.exists() or target.is_symlink():
        raise SnapshotError(f"{target} exists; a snapshot never overwrites")
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(_open_source(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst, pages=-1)
        _seal(dst, target)
