"""A staged backup is restored into a fresh root, or refused (issue #731, slice 4)."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from mcp_server.core.backup_manifest import (
    MANIFEST_NAME,
    ManifestError,
)
from mcp_server.handlers import backup_restore as backup_restore_module
from mcp_server.handlers.backup_restore import RestoreError, restore_backup
from mcp_server.handlers.backup_snapshot import snapshot_backup
from mcp_server.infrastructure.backup_scan import BackupScanError
from mcp_server.infrastructure.sqlite_snapshot import SnapshotError
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.handlers._backup_restore_fakes import (
    PAGE,
    files_backup,
    hand_made_backup,
    tree,
    write,
)

_STORE = "methodology/memory.db"


def test_a_live_store_is_backed_up_and_its_memory_read_from_the_restored_root(
    tmp_path,
):
    root, archive, target = tmp_path / "root", tmp_path / "backup", tmp_path / "new"
    live = SqliteMemoryStore(str(root / _STORE))
    try:
        memory_id = live.insert_memory(
            {"content": "the restore is verified", "tags": ["t"], "domain": "d"}
        )
        write(root, PAGE, b"page")
        taken = snapshot_backup(root, archive, "sqlite")
    finally:
        live.close()

    restored_manifest = restore_backup(archive, target)

    assert restored_manifest == taken
    restored = SqliteMemoryStore(str(target / _STORE))
    try:
        memory = restored.get_memory(memory_id)
    finally:
        restored.close()
    assert memory["content"] == "the restore is verified"
    assert memory["domain"] == "d"
    assert (target / PAGE).read_bytes() == b"page"


def test_the_restored_root_holds_the_manifest_files_and_nothing_else(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "deep" / "new"
    write(archive, "methodology/telemetry.jsonl", b"not a class A file")
    before = tree(archive)

    restore_backup(archive, target)

    assert tree(target) == {
        "methodology": None,
        "methodology/artifacts": None,
        "methodology/wiki": None,
        "methodology/wiki/adr": None,
        PAGE: b"page",
    }
    assert not (tmp_path / "deep" / "new.partial").exists()
    assert tree(archive) == before


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_restored_root_is_owner_only_whatever_the_umask(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    previous = os.umask(0o022)
    try:
        restore_backup(archive, target)
    finally:
        os.umask(previous)
    modes = {
        p.relative_to(target).as_posix(): stat.S_IMODE(p.stat().st_mode)
        for p in [target, *target.rglob("*")]
    }
    assert modes == {
        ".": 0o700,
        "methodology": 0o700,
        "methodology/artifacts": 0o700,
        "methodology/wiki": 0o700,
        "methodology/wiki/adr": 0o700,
        PAGE: 0o600,
    }


def test_a_tree_without_its_manifest_is_not_a_backup(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    (archive / MANIFEST_NAME).unlink()
    message = rf"backup holds no {MANIFEST_NAME}: not a complete backup$"
    with pytest.raises(RestoreError, match=message):
        restore_backup(archive, target)
    assert not target.exists() and not (tmp_path / "new.partial").exists()


@pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)
def test_a_linked_manifest_is_not_read(tmp_path):
    archive = files_backup(tmp_path)
    manifest = archive / MANIFEST_NAME
    manifest.rename(tmp_path / "elsewhere.json")
    manifest.symlink_to(tmp_path / "elsewhere.json")
    with pytest.raises(RestoreError, match="holds no"):
        restore_backup(archive, tmp_path / "new")


def test_a_manifest_of_another_version_is_refused(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    manifest = archive / MANIFEST_NAME
    text = manifest.read_text(encoding="ascii")
    manifest.write_text(text.replace('"version": 1', '"version": 2'), encoding="ascii")
    with pytest.raises(ManifestError, match="manifest version 2, this Cortex reads 1"):
        restore_backup(archive, target)
    assert not target.exists() and not (tmp_path / "new.partial").exists()


def test_a_manifest_that_is_not_utf8_is_refused_as_not_json(tmp_path):
    archive = files_backup(tmp_path)
    (archive / MANIFEST_NAME).write_bytes(b"\xff\xfe{}")
    with pytest.raises(ManifestError, match="^not JSON"):
        restore_backup(archive, tmp_path / "new")


def test_a_managed_backup_is_refused_until_its_cluster_can_be_restored(tmp_path):
    archive = tmp_path / "backup"
    write(archive, "methodology/managed-pg/cluster/PG_VERSION", b"17\n")
    write(archive, "methodology/managed-pg/password", b"secret")
    hand_made_backup(archive, "managed")
    with pytest.raises(ManifestError) as refused:
        restore_backup(archive, tmp_path / "new")
    assert str(refused.value) == (
        "a managed PostgreSQL backup cannot be restored yet (issue #731)"
    )
    assert not (tmp_path / "new").exists() and not (tmp_path / "new.partial").exists()


def test_an_incomplete_or_altered_backup_is_refused_before_anywrite(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    write(archive, PAGE, b"edited")
    write(archive, "methodology/wiki/adr/2.md", b"added")
    (archive / "methodology" / "artifacts").rmdir()

    with pytest.raises(RestoreError) as refused:
        restore_backup(archive, target)

    assert str(refused.value) == (
        f"the backup {archive} does not match its manifest: "
        f"methodology/wiki/adr/1.md: content differs from the manifest; "
        f"methodology/wiki/adr/2.md: not in the manifest; "
        f"methodology/artifacts: absent"
    )
    assert not target.exists() and not (tmp_path / "new.partial").exists()


def test_a_sqlite_backup_without_its_store_is_refused(tmp_path):
    root, archive = tmp_path / "root", tmp_path / "backup"
    SqliteMemoryStore(str(root / _STORE)).close()
    snapshot_backup(root, archive, "sqlite")
    (archive / _STORE).unlink()
    with pytest.raises(ManifestError, match=r"memory\.db is required for a sqlite"):
        restore_backup(archive, tmp_path / "new")
    assert not (tmp_path / "new").exists() and not (tmp_path / "new.partial").exists()


@pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)
def test_a_backup_that_holds_a_link_is_refused(tmp_path):
    archive = files_backup(tmp_path)
    (archive / "methodology" / "wiki" / "link.md").symlink_to(archive / PAGE)
    with pytest.raises(BackupScanError, match="symbolic link"):
        restore_backup(archive, tmp_path / "new")
    assert not (tmp_path / "new.partial").exists()


def test_a_store_sqlite_cannot_read_is_refused_though_its_digest_matches(tmp_path):
    archive, target = tmp_path / "backup", tmp_path / "new"
    write(archive, _STORE, b"not a database" * 100)
    hand_made_backup(archive, "sqlite")
    with pytest.raises(SnapshotError, match="is not a readable SQLite database"):
        restore_backup(archive, target)
    assert not target.exists() and not (tmp_path / "new.partial").exists()


def test_a_backup_without_a_sqlite_store_is_not_opened_by_sqlite(tmp_path, monkeypatch):
    archive = files_backup(tmp_path)
    checked = []
    monkeypatch.setattr(backup_restore_module, "check_snapshot", checked.append)
    restore_backup(archive, tmp_path / "new")
    assert checked == []


def test_only_the_store_of_a_sqlite_backup_is_opened_by_sqlite(tmp_path, monkeypatch):
    root, archive = tmp_path / "root", tmp_path / "backup"
    SqliteMemoryStore(str(root / _STORE)).close()
    write(root, PAGE, b"page")
    snapshot_backup(root, archive, "sqlite")
    checked = []
    monkeypatch.setattr(backup_restore_module, "check_snapshot", checked.append)
    restore_backup(archive, tmp_path / "new")
    assert checked == [archive / "methodology" / "memory.db"]
