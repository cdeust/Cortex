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
source is refused instead of being created empty. Both connections come from
``infrastructure/db_connect.py`` (ADR-1110), and the copy is created ``0o600``
before SQLite opens it (ADR-1112), as the store is.

source: issue #731; docs/audits/owned-resources-backup-2026-11-05.md §3, §5;
SQLite online backup API, https://www.sqlite.org/backup.html (Python's
``Connection.backup`` defaults to ``pages=-1``): a single
``sqlite3_backup_step()`` call with a negative page count "copies the entire
source database in one call", holding one read lock on the source throughout.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from mcp_server.infrastructure.db_connect import sqlite_connect
from mcp_server.shared.private_paths import create_private_file


class SnapshotError(OSError):
    """A store cannot be copied as one consistent, self-contained file."""


def _open_source(source: Path) -> sqlite3.Connection:
    if not source.is_file() or source.is_symlink():
        raise SnapshotError(f"{source} is not a regular SQLite file")
    return sqlite_connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)


def _seal(target: sqlite3.Connection) -> None:
    """Make the copy one file and refuse it if SQLite does not call it intact."""
    mode = target.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
    if mode != "delete":
        raise SnapshotError(f"the copy kept journal_mode={mode}")
    verdict = [row[0] for row in target.execute("PRAGMA integrity_check")]
    if verdict != ["ok"]:
        raise SnapshotError(f"the copy failed integrity_check: {'; '.join(verdict)}")


def snapshot_sqlite(source: Path, target: Path) -> None:
    """Write the database at ``source`` to the new file ``target``, as of one instant.

    ``target`` must not exist; its directory must.
    """
    if target.exists() or target.is_symlink():
        raise SnapshotError(f"{target} exists; a snapshot never overwrites")
    if not target.parent.is_dir():
        raise SnapshotError(f"{target.parent} is not a directory")
    with closing(_open_source(source)) as src:
        create_private_file(target)
        with closing(sqlite_connect(str(target))) as dst:
            src.backup(dst)  # pages=-1 by default: one step
            _seal(dst)
