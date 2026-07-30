"""Tests for shared.platform cross-platform primitives.

These run on any host: the OS-specific behavior is exercised by mocking
``os.sep`` and ``$HOME`` rather than requiring a Windows runner. The
windows-latest CI job provides the real-NT proof on top of these.

source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.1, §5.2, §5.3
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp_server.shared import platform as plat


def test_home_dir_prefers_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert plat.home_dir() == tmp_path


def test_home_dir_falls_back_to_path_home(monkeypatch):
    monkeypatch.delenv("HOME", raising=False)
    assert plat.home_dir() == Path.home()


def test_python_executable_is_current_interpreter():
    assert plat.python_executable() == sys.executable


def test_to_posix_noop_on_forward_slash():
    assert plat.to_posix("a/b/c.py") == "a/b/c.py"


def test_to_posix_accepts_pathlike():
    assert plat.to_posix(Path("a") / "b" / "c.py") == "a/b/c.py"


def test_to_posix_rewrites_backslashes_when_sep_is_backslash(monkeypatch):
    # Simulate the Windows separator so the rewrite branch runs on any host.
    monkeypatch.setattr(plat.os, "sep", "\\")
    assert plat.to_posix("a\\b\\c.py") == "a/b/c.py"
