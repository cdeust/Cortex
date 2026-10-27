"""Contract of resolve_bash: an absolute, usable bash or a loud failure.

source: ADR-1101 (issue #689)"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mcp_server.shared.platform import IS_WINDOWS, BashNotFoundError, resolve_bash


def _bash_exe(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / "bash.exe"
    exe.write_text("")
    return exe


def _path(*dirs: Path) -> str:
    return os.pathsep.join(str(d) for d in dirs)


def test_windows_skips_the_system32_stub_for_the_next_bash_on_path(tmp_path):
    _bash_exe(tmp_path / "Windows" / "System32")
    git_bash = _bash_exe(tmp_path / "Git" / "usr" / "bin")
    path_env = _path(tmp_path / "Windows" / "System32", git_bash.parent)
    assert resolve_bash(path_env=path_env, windows=True) == str(git_bash)


def test_windows_skips_the_windowsapps_stub(tmp_path):
    apps = tmp_path / "AppData" / "Local" / "Microsoft" / "WindowsApps"
    _bash_exe(apps)
    git_bash = _bash_exe(tmp_path / "Git" / "bin")
    assert resolve_bash(path_env=_path(apps, git_bash.parent), windows=True) == str(
        git_bash
    )


def test_windows_finds_git_bash_from_git_cmd_when_path_has_no_bash(tmp_path):
    # Stock Git for Windows: PATH holds Git\cmd (git.exe only). Measured on a
    # Windows 11 machine, 2026-10-13. source: ADR-1101
    root = tmp_path / "Git"
    (root / "cmd").mkdir(parents=True)
    (root / "cmd" / "git.exe").write_text("")
    git_bash = _bash_exe(root / "bin")
    path_env = _path(root / "cmd")
    assert resolve_bash(path_env=path_env, windows=True) == str(git_bash)


def test_windows_with_only_stubs_fails_naming_git_for_windows(tmp_path):
    stub = _bash_exe(tmp_path / "Windows" / "System32")
    with pytest.raises(BashNotFoundError) as raised:
        resolve_bash(path_env=_path(stub.parent), windows=True)
    message = str(raised.value)
    assert "Git for Windows" in message
    assert "WSL" in message
    assert str(stub) in message


def test_posix_without_bash_fails_loudly(tmp_path):
    with pytest.raises(BashNotFoundError, match="Git for Windows"):
        resolve_bash(path_env=str(tmp_path), windows=False)


def test_posix_returns_an_absolute_path(tmp_path):
    bash = tmp_path / "bash"
    bash.write_text("#!/bin/sh\n")
    bash.chmod(0o755)
    assert resolve_bash(path_env=str(tmp_path), windows=False) == str(bash)


def test_the_host_resolves_a_bash_that_is_not_a_wsl_stub():
    resolved = resolve_bash()
    assert os.path.isabs(resolved)
    if IS_WINDOWS:
        parts = {part.lower() for part in Path(resolved).parts}
        assert not parts & {"system32", "windowsapps"}, resolved
