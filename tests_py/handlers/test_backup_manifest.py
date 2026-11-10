"""The backup manifest of a real Cortex root (issue #731, slice 2)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from mcp_server.core.backup_manifest import ManifestError, parse_manifest, to_json
from mcp_server.handlers.backup_manifest import backup_manifest


def _write(root, relative: str, data: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_a_sqlite_root_is_digested_entry_by_entry(tmp_path):
    _write(tmp_path, "methodology/memory.db", b"db")
    _write(tmp_path, "methodology/wiki/adr/1.md", b"page")
    _write(tmp_path, "methodology/session-log.json", b"[]")
    _write(tmp_path, "methodology/telemetry.jsonl", b"class S, not carried")
    now = datetime(2026, 11, 10, 3, 0, 0, 123456, tzinfo=timezone.utc)

    manifest = backup_manifest(tmp_path, "sqlite", now=now)

    assert manifest["created_at"] == "2026-11-10T03:00:00+00:00"
    entries = {e["name"]: e for e in manifest["entries"]}
    assert entries["sqlite_store"]["files"] == [
        {
            "path": "methodology/memory.db",
            "sha256": hashlib.sha256(b"db").hexdigest(),
            "size": 2,
        }
    ]
    assert [f["path"] for f in entries["wiki"]["files"]] == [
        "methodology/wiki/adr/1.md"
    ]
    assert entries["session_log"]["present"] is True
    assert entries["artifacts"]["present"] is False
    carried = [f["path"] for e in manifest["entries"] for f in e["files"]]
    assert "methodology/telemetry.jsonl" not in carried
    assert parse_manifest(to_json(manifest)) == manifest


def test_created_at_defaults_to_now_in_utc(tmp_path):
    _write(tmp_path, "methodology/memory.db", b"db")
    before = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = datetime.fromisoformat(backup_manifest(tmp_path, "sqlite")["created_at"])
    assert stamp.utcoffset().total_seconds() == 0
    assert before <= stamp <= datetime.now(timezone.utc)


def test_a_sqlite_root_without_its_database_is_refused(tmp_path):
    with pytest.raises(ManifestError, match=r"methodology/memory\.db is required"):
        backup_manifest(tmp_path, "sqlite")


def test_a_managed_root_carries_the_cluster_files_and_the_password(tmp_path):
    _write(tmp_path, "methodology/managed-pg/cluster/PG_VERSION", b"18\n")
    _write(tmp_path, "methodology/managed-pg/password", b"pw")
    _write(tmp_path, "methodology/managed-pg/status.json", b"{}")
    entries = {e["name"]: e for e in backup_manifest(tmp_path, "managed")["entries"]}
    assert [f["path"] for f in entries["managed_cluster"]["files"]] == [
        "methodology/managed-pg/cluster/PG_VERSION"
    ]
    assert entries["managed_password"]["secret"] is True
    carried = [f["path"] for e in entries.values() for f in e["files"]]
    assert "methodology/managed-pg/status.json" not in carried
