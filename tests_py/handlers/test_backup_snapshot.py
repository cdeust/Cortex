"""A backup of a live Cortex root is staged and then digested (issue #731, slice 3)."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing

import pytest

from mcp_server.core.backup_manifest import ManifestError, parse_manifest, to_json
from mcp_server.handlers.backup_snapshot import snapshot_backup
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
