"""One file at the top of a staging tree is written and read (issue #731, slice 4)."""

from __future__ import annotations

import os
import stat
import sys

import pytest

from mcp_server.infrastructure.backup_stage import read_text_file, write_new_file


def test_a_written_file_is_read_back(tmp_path):
    write_new_file(tmp_path, "manifest.json", b'{"a": 1}\n')
    assert (tmp_path / "manifest.json").read_bytes() == b'{"a": 1}\n'
    assert read_text_file(tmp_path, "manifest.json") == '{"a": 1}\n'


def test_an_existing_file_is_never_written_over(tmp_path):
    (tmp_path / "manifest.json").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        write_new_file(tmp_path, "manifest.json", b"new")
    assert (tmp_path / "manifest.json").read_bytes() == b"keep"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_written_file_is_owner_only_whatever_the_umask(tmp_path):
    previous = os.umask(0o022)
    try:
        write_new_file(tmp_path, "manifest.json", b"{}")
    finally:
        os.umask(previous)
    assert stat.S_IMODE((tmp_path / "manifest.json").stat().st_mode) == 0o600


def test_an_absent_file_and_a_directory_are_not_read(tmp_path):
    (tmp_path / "a-directory").mkdir()
    assert read_text_file(tmp_path, "absent.json") is None
    assert read_text_file(tmp_path, "a-directory") is None


@pytest.mark.skipif(
    sys.platform == "win32", reason="creating a symlink needs a privilege on Windows"
)
def test_a_linked_file_is_not_read(tmp_path):
    (tmp_path / "real.json").write_bytes(b"{}")
    (tmp_path / "manifest.json").symlink_to(tmp_path / "real.json")
    assert read_text_file(tmp_path, "manifest.json") is None


def test_text_is_read_as_utf8_and_a_foreign_byte_is_replaced(tmp_path):
    (tmp_path / "manifest.json").write_bytes("é".encode() + b"\xff")
    assert read_text_file(tmp_path, "manifest.json") == "é�"
