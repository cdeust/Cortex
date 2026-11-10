"""A backup of a live Cortex root is staged and then digested (issue #731, slice 3)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import sys
from contextlib import closing

import pytest

from mcp_server.core.backup_manifest import ManifestError, parse_manifest, to_json
from mcp_server.handlers import backup_snapshot as backup_snapshot_module
from mcp_server.handlers.backup_snapshot import snapshot_backup
from mcp_server.infrastructure.backup_scan import BackupScanError
from mcp_server.infrastructure.backup_stage import StagingError


def _write(root, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _live_store(root):
    path = root / "methodology" / "memory.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE memories (content TEXT)")
    connection.execute("INSERT INTO memories VALUES ('only in the wal')")
    connection.commit()
    return connection


def test_a_live_sqlite_root_is_staged_with_its_wal_and_digested(tmp_path):
    root, staging = tmp_path / "root", tmp_path / "staging"
    writer = _live_store(root)
    _write(root, "methodology/wiki/adr/1.md", b"page")
    _write(root, "methodology/telemetry.jsonl", b"class S, not carried")
    (root / "methodology" / "artifacts").mkdir()

    manifest = snapshot_backup(root, staging, "sqlite")
    writer.close()

    with closing(sqlite3.connect(staging / "methodology" / "memory.db")) as copy:
        assert copy.execute("SELECT content FROM memories").fetchall() == [
            ("only in the wal",)
        ]
    assert sorted(p.name for p in (staging / "methodology").iterdir()) == [
        "artifacts",
        "memory.db",
        "wiki",
    ]
    entries = {e["name"]: e for e in manifest["entries"]}
    store = (staging / "methodology" / "memory.db").read_bytes()
    assert entries["sqlite_store"]["files"][0]["sha256"] == (
        hashlib.sha256(store).hexdigest()
    )
    assert entries["wiki"]["files"][0]["path"] == "methodology/wiki/adr/1.md"
    assert entries["artifacts"]["present"] is True
    assert entries["artifacts"]["files"] == []
    assert parse_manifest(to_json(manifest)) == manifest


def test_a_sqlite_root_without_its_store_is_refused(tmp_path):
    with pytest.raises(ManifestError, match=r"methodology/memory\.db is required"):
        snapshot_backup(tmp_path / "root", tmp_path / "staging", "sqlite")


def test_a_postgresql_root_stages_its_files_only(tmp_path):
    root, staging = tmp_path / "root", tmp_path / "staging"
    _write(root, "methodology/session-log.json", b"[]")
    manifest = snapshot_backup(root, staging, "postgresql")
    assert (staging / "methodology" / "session-log.json").read_bytes() == b"[]"
    assert [e["name"] for e in manifest["entries"] if e["present"]] == ["session_log"]


def test_a_managed_root_is_refused_until_its_cluster_can_be_copied(tmp_path):
    with pytest.raises(ManifestError, match="managed PostgreSQL"):
        snapshot_backup(tmp_path / "root", tmp_path / "staging", "managed")
    assert not (tmp_path / "staging").exists()


def test_a_staging_root_that_holds_anything_is_refused(tmp_path):
    root, staging = tmp_path / "root", tmp_path / "staging"
    _live_store(root).close()
    _write(staging, "left.txt", b"x")
    with pytest.raises(StagingError, match="not empty"):
        snapshot_backup(root, staging, "sqlite")


def test_a_staging_root_inside_the_cortex_root_is_refused(tmp_path):
    _live_store(tmp_path).close()
    with pytest.raises(StagingError, match="inside the Cortex root"):
        snapshot_backup(tmp_path, tmp_path / "methodology" / "backup", "sqlite")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_every_staged_entry_is_owner_only_whatever_the_umask(tmp_path):
    root, staging = tmp_path / "root", tmp_path / "staging"
    _live_store(root).close()
    _write(root, "methodology/wiki/adr/1.md", b"page")
    _write(root, ".capture-worker/spool/1.json", b"{}")
    staging.mkdir(mode=0o755)
    staging.chmod(0o755)
    previous = os.umask(0o022)
    try:
        snapshot_backup(root, staging, "sqlite")
    finally:
        os.umask(previous)
    modes = {
        path.relative_to(staging).as_posix(): stat.S_IMODE(path.lstat().st_mode)
        for path in [staging, *staging.rglob("*")]
    }
    assert modes.pop(".") == 0o700
    assert modes and all(
        mode == (0o700 if (staging / name).is_dir() else 0o600)
        for name, mode in modes.items()
    ), modes


@pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)
def test_a_linked_methodology_directory_is_refused_for_the_store(tmp_path):
    root, staging, outside = tmp_path / "root", tmp_path / "staging", tmp_path / "out"
    _live_store(outside).close()
    root.mkdir()
    (root / "methodology").symlink_to(outside / "methodology")
    with pytest.raises(BackupScanError, match="symbolic link"):
        snapshot_backup(root, staging, "sqlite")
    assert not (staging / "methodology" / "memory.db").exists()


def test_the_spool_is_staged_before_the_store(tmp_path, monkeypatch):
    """A payload drained between the two copies must still be in the spool copy."""
    root, staging = tmp_path / "root", tmp_path / "staging"
    _live_store(root).close()
    _write(root, ".capture-worker/spool/1.json", b"{}")
    seen = []
    real = backup_snapshot_module.snapshot_sqlite

    def snapshot_after_spool(source, target):
        seen.append((staging / ".capture-worker/spool/1.json").exists())
        (root / ".capture-worker/spool/1.json").unlink()  # the drainer ran
        real(source, target)

    monkeypatch.setattr(backup_snapshot_module, "snapshot_sqlite", snapshot_after_spool)
    manifest = snapshot_backup(root, staging, "sqlite")
    assert seen == [True]
    entries = {e["name"]: e for e in manifest["entries"]}
    assert [f["path"] for f in entries["capture_spool"]["files"]] == [
        ".capture-worker/spool/1.json"
    ]
