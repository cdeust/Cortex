"""Existing installs are made owner-only at startup (ADR-1112)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from mcp_server.shared import private_paths

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


@pytest.fixture
def legacy_install(tmp_path, monkeypatch):
    """A tree as a pre-fix install left it: umask 022/002 modes."""
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)
    methodology = tmp_path / "claude" / "methodology"
    (methodology / "wiki" / "notes").mkdir(parents=True)
    (methodology / "bin").mkdir()
    files = {
        methodology / "memory.db": 0o644,
        methodology / "telemetry.jsonl": 0o664,
        methodology / "consolidate.log": 0o644,
        methodology / "wiki" / "notes" / "a.md": 0o644,
        methodology / "bin" / "pipeline": 0o755,
        tmp_path / "claude" / "brain-index.json": 0o644,
    }
    for path, mode in files.items():
        path.write_text("x")
        path.chmod(mode)
    for directory in (methodology, methodology / "wiki", methodology / "bin"):
        directory.chmod(0o775)
    outside = tmp_path / "outside.txt"
    outside.write_text("not ours")
    outside.chmod(0o644)
    (methodology / "link").symlink_to(outside)
    return methodology, files, outside


@posix_only
def test_a_legacy_tree_becomes_owner_only_and_symlinks_are_not_followed(
    legacy_install,
):
    methodology, files, outside = legacy_install
    changed = private_paths.harden_private_storage()
    assert changed >= len(files)
    for directory in (methodology, methodology / "wiki", methodology / "bin"):
        assert _mode(directory) == 0o700, directory
    for path in files:
        expected = 0o700 if path.name == "pipeline" else 0o600  # exec bit kept
        assert _mode(path) == expected, path
    assert _mode(outside) == 0o644  # the symlink's target is not ours


@posix_only
def test_the_tree_walk_runs_once_per_install_the_roots_every_time(legacy_install):
    methodology, files, _outside = legacy_install
    private_paths.harden_private_storage()
    late = methodology / "late.log"
    late.write_text("x")
    late.chmod(0o644)
    methodology.chmod(0o755)
    assert private_paths.harden_private_storage() == 1  # the root, not the walk
    assert _mode(methodology) == 0o700
    assert _mode(late) == 0o644  # created raw after the stamp; the root shields it


@posix_only
def test_writes_under_the_roots_create_private_directories(tmp_path, monkeypatch):
    from mcp_server.shared import gated_files

    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    old = os.umask(0o022)
    try:
        target = tmp_path / "claude" / "methodology" / "deep" / "er" / "f.json"
        gated_files.write_json(target, {"k": 1})
    finally:
        os.umask(old)
    assert _mode(target) == 0o600
    for level in (target.parent, target.parent.parent, target.parents[2]):
        assert _mode(level) == 0o700, level


def test_is_private_knows_the_roots_and_nothing_else(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    assert private_paths.is_private(tmp_path / "claude" / "methodology" / "x.db")
    assert private_paths.is_private(tmp_path / "claude" / ".capture-worker" / "s")
    assert private_paths.is_private(tmp_path / "claude" / "brain-index.json")
    assert private_paths.is_private(private_paths.cortex_cache_dir() / "mcp-logs")
    assert not private_paths.is_private(tmp_path / "claude" / "settings.json")
    assert not private_paths.is_private(tmp_path / "repo" / "CLAUDE.md")


def test_windows_roots_get_a_user_only_inherited_acl(tmp_path, monkeypatch):
    """On Windows chmod cannot express owner-only; the roots get an ACL that
    removes inherited entries and grants the user full control, inherited by
    every file and directory below (icacls OI/CI)."""
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)
    monkeypatch.setenv("USERNAME", "jane")
    monkeypatch.setenv("USERDOMAIN", "HOST")
    (tmp_path / "claude" / "methodology").mkdir(parents=True)
    commands: list[list[str]] = []
    private_paths.harden_private_storage(platform="win32", run=commands.append)
    assert commands == [
        [
            "icacls",
            str(tmp_path / "claude" / "methodology"),
            "/inheritance:r",
            "/grant:r",
            "HOST\\jane:(OI)(CI)F",
        ]
    ]


@posix_only
def test_a_path_that_cannot_be_tightened_is_reported_not_hidden(
    legacy_install, monkeypatch, capsys
):
    def refuse(fd, mode):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(private_paths.os, "fchmod", refuse)
    private_paths.harden_at_startup()
    err = capsys.readouterr().err
    assert "could not make personal data owner-only" in err
    assert "methodology" in err


def test_the_cache_root_follows_the_data_root_unless_told_otherwise(
    tmp_path, monkeypatch
):
    for name in ("CORTEX_CACHE_DIR", "XDG_CACHE_HOME", "CORTEX_CLAUDE_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert private_paths.cortex_cache_dir() == tmp_path / "home" / ".cache" / "cortex"
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    assert private_paths.cortex_cache_dir() == tmp_path / "claude" / "cache" / "cortex"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert private_paths.cortex_cache_dir() == tmp_path / "xdg" / "cortex"
    monkeypatch.setenv("CORTEX_CACHE_DIR", str(tmp_path / "explicit"))
    assert private_paths.cortex_cache_dir() == tmp_path / "explicit"


def _outside_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A directory and a file outside every data root, umask modes."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    secret = elsewhere / "notes.txt"
    secret.write_text("not Cortex data")
    elsewhere.chmod(0o755)
    secret.chmod(0o644)
    return elsewhere, secret


@posix_only
@pytest.mark.parametrize("root_name", ["methodology", ".capture-worker"])
def test_a_symlinked_root_is_not_followed(tmp_path, monkeypatch, root_name):
    """Review of #775, B3: a data root that is a symlink let the hardening
    chmod (and walk) the tree it points to: measured 0755/0644 outside the
    roots turned 0700/0600."""
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)
    (tmp_path / "claude").mkdir()
    if root_name != "methodology":
        (tmp_path / "claude" / "methodology").mkdir()
    elsewhere, secret = _outside_tree(tmp_path)
    (tmp_path / "claude" / root_name).symlink_to(elsewhere)
    private_paths.harden_private_storage()
    assert (_mode(elsewhere), _mode(secret)) == (0o755, 0o644)


@posix_only
def test_a_symlinked_directory_level_is_not_chmodded(tmp_path, monkeypatch):
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)
    methodology = tmp_path / "claude" / "methodology"
    methodology.mkdir(parents=True)
    elsewhere, _secret = _outside_tree(tmp_path)
    (methodology / "wiki").symlink_to(elsewhere)
    private_paths.ensure_private_dir(methodology / "wiki" / "adr")
    assert _mode(elsewhere) == 0o755


@posix_only
def test_a_symlinked_root_is_reported_at_startup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CORTEX_CACHE_DIR", raising=False)
    (tmp_path / "claude").mkdir()
    elsewhere, _secret = _outside_tree(tmp_path)
    (tmp_path / "claude" / "methodology").symlink_to(elsewhere)
    private_paths.harden_at_startup()
    assert "is a symbolic link" in capsys.readouterr().err


@pytest.mark.parametrize("user", ["", "   "])
def test_an_empty_windows_user_name_is_refused(tmp_path, monkeypatch, user):
    """Review of #775, N5: an empty USERNAME made the icacls principal empty
    (``:(OI)(CI)F`` or ``HOST\\:(OI)(CI)F``) after inheritance was removed."""
    monkeypatch.setenv("USERNAME", user)
    monkeypatch.setenv("USERDOMAIN", "HOST")
    commands: list[list[str]] = []
    with pytest.raises(OSError, match="USERNAME"):
        private_paths.restrict_windows_acl(tmp_path, commands.append)
    assert commands == []
