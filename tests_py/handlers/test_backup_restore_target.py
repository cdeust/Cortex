"""Where a restore writes, and what a failed one leaves (issue #731, slice 4)."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from mcp_server.core.backup_manifest import MANIFEST_NAME, parse_manifest, to_json
from mcp_server.handlers import backup_restore as backup_restore_module
from mcp_server.handlers.backup_restore import RestoreError, restore_backup
from mcp_server.handlers.backup_snapshot import snapshot_backup
from mcp_server.infrastructure.backup_stage import StagingError
from tests_py.handlers._backup_restore_fakes import PAGE, files_backup, tree, write


def test_an_existing_target_is_never_written_over(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    write(target, "methodology/session-log.json", b"an install")
    before = tree(target)
    with pytest.raises(RestoreError, match=r"new exists; a restore never writes over"):
        restore_backup(archive, target)
    assert tree(target) == before
    assert not (tmp_path / "new.partial").exists()


def test_an_existing_empty_target_is_refused_too(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    target.mkdir()
    with pytest.raises(RestoreError, match="exists"):
        restore_backup(archive, target)
    assert list(target.iterdir()) == []


@pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)
def test_a_target_that_is_a_dangling_link_is_refused(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    target.symlink_to(tmp_path / "nowhere")
    with pytest.raises(RestoreError, match="exists"):
        restore_backup(archive, target)
    assert not (tmp_path / "nowhere").exists()


def test_a_target_inside_the_backup_is_refused(tmp_path):
    archive = files_backup(tmp_path)
    before = tree(archive)
    with pytest.raises(RestoreError, match=r"inside is inside the backup .*backup$"):
        restore_backup(archive, archive / "inside")
    assert tree(archive) == before


def test_what_an_earlier_failed_restore_left_is_not_built_upon(tmp_path):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    write(tmp_path / "new.partial", "methodology/leftover", b"half a restore")
    with pytest.raises(StagingError, match=r"new\.partial is not empty"):
        restore_backup(archive, target)
    assert not target.exists()


def test_a_file_that_vanishes_from_the_backup_during_the_restore_fails_it(
    tmp_path, monkeypatch
):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    real_prepare = backup_restore_module.prepare_staging

    def prepare_then_lose_the_page(root, staging):
        real_prepare(root, staging)
        (archive / PAGE).unlink()

    monkeypatch.setattr(
        backup_restore_module, "prepare_staging", prepare_then_lose_the_page
    )
    with pytest.raises(FileNotFoundError):
        restore_backup(archive, target)
    assert not target.exists()


def test_a_copy_that_differs_from_the_manifest_never_becomes_the_target(
    tmp_path, monkeypatch
):
    archive, target = files_backup(tmp_path), tmp_path / "new"
    real_copy = backup_restore_module.copy_files

    def copy_then_damage(root, staging, paths, *, consumed_ok):
        assert consumed_ok is False  # no file of a backup may vanish unnoticed
        real_copy(root, staging, paths, consumed_ok=consumed_ok)
        if PAGE in paths:
            (staging / PAGE).write_bytes(b"torn")

    monkeypatch.setattr(backup_restore_module, "copy_files", copy_then_damage)
    with pytest.raises(RestoreError) as refused:
        restore_backup(archive, target)
    partial = tmp_path / "new.partial"
    assert str(refused.value) == (
        f"the restored copy {partial} does not match its manifest: "
        f"{PAGE}: content differs from the manifest"
    )
    assert not target.exists()
    assert (partial / PAGE).read_bytes() == b"torn"


def test_the_staged_manifest_is_the_one_returned(tmp_path):
    root, archive = tmp_path / "root", tmp_path / "backup"
    write(root, PAGE, b"page")
    manifest = snapshot_backup(root, archive, "postgresql")
    text = (archive / MANIFEST_NAME).read_bytes()
    assert text == to_json(manifest).encode("ascii")
    assert parse_manifest(text.decode("ascii")) == manifest


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_staged_manifest_is_owner_only_whatever_the_umask(tmp_path):
    root, archive = tmp_path / "root", tmp_path / "backup"
    write(root, PAGE, b"page")
    previous = os.umask(0o022)
    try:
        snapshot_backup(root, archive, "postgresql")
    finally:
        os.umask(previous)
    assert stat.S_IMODE((archive / MANIFEST_NAME).stat().st_mode) == 0o600
