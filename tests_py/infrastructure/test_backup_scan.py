"""Reading and digesting backup resources (issue #731, slice 2)."""

from __future__ import annotations

import hashlib
import os
import socket
import sys

import pytest

from mcp_server.infrastructure.backup_scan import BackupScanError, scan_resource


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_an_absent_resource_is_none(tmp_path):
    assert scan_resource(tmp_path, "methodology/memory.db", "file") is None
    assert scan_resource(tmp_path, "methodology/wiki", "dir") is None


def test_a_file_resource_is_one_record_with_its_digest_and_size(tmp_path):
    (tmp_path / "methodology").mkdir()
    (tmp_path / "methodology" / "memory.db").write_bytes(b"sqlite bytes")
    assert scan_resource(tmp_path, "methodology/memory.db", "file") == [
        ("methodology/memory.db", _sha(b"sqlite bytes"), 12)
    ]


def test_an_empty_file_has_size_zero_and_the_empty_digest(tmp_path):
    (tmp_path / "f").write_bytes(b"")
    assert scan_resource(tmp_path, "f", "file") == [("f", _sha(b""), 0)]


def test_a_directory_is_every_file_below_it_sorted_with_posix_paths(tmp_path):
    wiki = tmp_path / "methodology" / "wiki"
    (wiki / "adr" / "deep").mkdir(parents=True)
    (wiki / "b.md").write_bytes(b"bb")
    (wiki / "a.md").write_bytes(b"a")
    (wiki / "adr" / "deep" / "c.md").write_bytes(b"ccc")
    (wiki / "empty").mkdir()
    assert scan_resource(tmp_path, "methodology/wiki", "dir") == [
        ("methodology/wiki/a.md", _sha(b"a"), 1),
        ("methodology/wiki/adr/deep/c.md", _sha(b"ccc"), 3),
        ("methodology/wiki/b.md", _sha(b"bb"), 2),
    ]


def test_an_empty_directory_is_present_with_no_records(tmp_path):
    (tmp_path / "spool").mkdir()
    assert scan_resource(tmp_path, "spool", "dir") == []


def test_a_resource_of_the_other_kind_is_refused(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "f").write_bytes(b"x")
    with pytest.raises(BackupScanError, match=r"d is expected to be a file$"):
        scan_resource(tmp_path, "d", "file")
    with pytest.raises(BackupScanError, match=r"f is expected to be a dir$"):
        scan_resource(tmp_path, "f", "dir")


needs_symlink = pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)


@needs_symlink
def test_a_symlinked_resource_is_refused_even_when_dangling(tmp_path):
    (tmp_path / "real").write_bytes(b"x")
    os.symlink(tmp_path / "real", tmp_path / "link")
    os.symlink(tmp_path / "missing", tmp_path / "dangling")
    for name in ("link", "dangling"):
        with pytest.raises(
            BackupScanError,
            match=r"is a symbolic link; a backup does not follow links$",
        ):
            scan_resource(tmp_path, name, "file")


@needs_symlink
def test_a_symlink_inside_a_directory_is_refused(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret").write_bytes(b"s")
    (tmp_path / "wiki").mkdir()
    os.symlink(outside, tmp_path / "wiki" / "escape")
    with pytest.raises(BackupScanError, match=r"escape is a symbolic link"):
        scan_resource(tmp_path, "wiki", "dir")


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no Unix sockets")
def test_a_special_file_inside_a_directory_is_refused(tmp_path):
    (tmp_path / "spool").mkdir()
    path = tmp_path / "spool" / "s"
    if len(str(path)) > 100:
        pytest.skip("socket path too long for AF_UNIX")
    server = socket.socket(socket.AF_UNIX)
    try:
        server.bind(str(path))
        with pytest.raises(
            BackupScanError, match=r"s is neither a regular file nor a directory$"
        ):
            scan_resource(tmp_path, "spool", "dir")
    finally:
        server.close()


# --- ancestors of a resource (review of #960) ---


@needs_symlink
def test_a_symlinked_ancestor_is_refused(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "memory.db").write_bytes(b"not this install's store")
    os.symlink(outside, tmp_path / "methodology")
    with pytest.raises(BackupScanError, match=r"methodology is a symbolic link"):
        scan_resource(tmp_path, "methodology/memory.db", "file")


@needs_symlink
def test_a_dangling_symlinked_ancestor_is_refused_not_absent(tmp_path):
    os.symlink(tmp_path / "missing", tmp_path / "methodology")
    with pytest.raises(BackupScanError, match=r"methodology is a symbolic link"):
        scan_resource(tmp_path, "methodology/wiki", "dir")


def test_a_deep_ancestor_that_is_a_file_is_refused(tmp_path):
    (tmp_path / "methodology").mkdir()
    (tmp_path / "methodology" / "managed-pg").write_bytes(b"x")
    with pytest.raises(BackupScanError, match=r"managed-pg is expected to be a dir$"):
        scan_resource(tmp_path, "methodology/managed-pg/password", "file")


def test_an_absent_ancestor_makes_the_resource_absent(tmp_path):
    (tmp_path / "methodology").mkdir()
    assert scan_resource(tmp_path, "methodology/managed-pg/password", "file") is None
    assert scan_resource(tmp_path, ".capture-worker/spool", "dir") is None


def test_two_absent_ancestors_make_the_resource_absent(tmp_path):
    assert scan_resource(tmp_path, "methodology/managed-pg/password", "file") is None
    assert scan_resource(tmp_path, "methodology/managed-pg/cluster", "dir") is None


def test_a_resource_below_real_ancestors_is_read(tmp_path):
    (tmp_path / "methodology" / "managed-pg").mkdir(parents=True)
    (tmp_path / "methodology" / "managed-pg" / "password").write_bytes(b"pw")
    assert scan_resource(tmp_path, "methodology/managed-pg/password", "file") == [
        ("methodology/managed-pg/password", _sha(b"pw"), 2)
    ]
