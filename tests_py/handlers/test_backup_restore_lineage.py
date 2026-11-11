"""A restored store keeps its version chains and source links (issue #731, slice 5).

The acceptance criterion reads "a consistent backup under concurrent writes,
preserving source links and version chains". Slice 3 proved that a copy holds
whole transactions; this file proves the property that matters to a reader of
the restored root: the supersession chain written by ``supersede_atomic`` is
still one unbroken chain, with both directions of every link, and every
version still names the source it was written from.
"""

from __future__ import annotations

import threading

from mcp_server.handlers.backup_restore import restore_backup
from mcp_server.handlers.backup_snapshot import snapshot_backup
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_STORE = "methodology/memory.db"


def _version(number: int) -> dict:
    return {
        "content": f"version {number}",
        "source": f"file:notes/v{number}.md",
        "tags": ["lineage"],
        "domain": "d",
    }


def _rows(store: SqliteMemoryStore) -> dict[int, dict]:
    rows = store._conn.execute(
        "SELECT id, content, source, supersedes_id, superseded_by_id FROM memories"
    ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def _assert_one_whole_chain(rows: dict[int, dict]) -> None:
    """Every link has its reverse, one head, and the walk back covers every row."""
    for memory_id, row in rows.items():
        if row["supersedes_id"] is not None:
            assert rows[row["supersedes_id"]]["superseded_by_id"] == memory_id
        if row["superseded_by_id"] is not None:
            assert rows[row["superseded_by_id"]]["supersedes_id"] == memory_id
    heads = [i for i, row in rows.items() if row["superseded_by_id"] is None]
    assert len(heads) == 1, heads
    walked, current = [], heads[0]
    while current is not None:
        walked.append(current)
        current = rows[current]["supersedes_id"]
    assert sorted(walked) == sorted(rows)
    for row in rows.values():
        number = row["content"].removeprefix("version ")
        assert row["source"] == f"file:notes/v{number}.md"


def _restored_rows(archive, target) -> dict[int, dict]:
    restore_backup(archive, target)
    restored = SqliteMemoryStore(str(target / _STORE))
    try:
        return _rows(restored)
    finally:
        restored.close()


def test_a_chain_and_its_sources_are_restored_link_for_link(tmp_path):
    root, archive, target = tmp_path / "root", tmp_path / "backup", tmp_path / "new"
    live = SqliteMemoryStore(str(root / _STORE))
    try:
        first = live.insert_memory(_version(0))
        for number in range(1, 4):
            new_id, _ = live.supersede_atomic(_version(number), first)
            assert new_id is not None
        live_rows = _rows(live)
        snapshot_backup(root, archive, "sqlite")
    finally:
        live.close()

    restored_rows = _restored_rows(archive, target)

    assert restored_rows == live_rows
    assert len(restored_rows) == 4
    _assert_one_whole_chain(restored_rows)


def test_backups_taken_while_the_chain_grows_restore_one_whole_chain(tmp_path):
    root = tmp_path / "root"
    live = SqliteMemoryStore(str(root / _STORE))
    first = live.insert_memory(_version(0))
    stop = threading.Event()
    failures: list[BaseException] = []

    def grow_chain() -> None:
        number = 1
        try:
            while not stop.is_set():
                new_id, _ = live.supersede_atomic(_version(number), first)
                assert new_id is not None
                number += 1
        except BaseException as exc:  # reported to the test thread below
            failures.append(exc)

    writer = threading.Thread(target=grow_chain)
    writer.start()
    try:
        archives = []
        for index in range(5):
            archive = tmp_path / f"backup-{index}"
            snapshot_backup(root, archive, "sqlite")
            archives.append(archive)
    finally:
        stop.set()
        writer.join()
        live.close()

    assert failures == []
    sizes = []
    for index, archive in enumerate(archives):
        rows = _restored_rows(archive, tmp_path / f"new-{index}")
        _assert_one_whole_chain(rows)
        sizes.append(len(rows))
    assert sizes == sorted(sizes)
    assert sizes[-1] > 1
