"""Tests for the cross-platform install lock (fcntl on POSIX, msvcrt on NT).

The import itself is the first assertion: on Windows the previous bare
``import fcntl`` crashed this module at load. The behavioral tests confirm
acquire/release and contention through the same ``install_lock()`` contract.

source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.4
"""

from __future__ import annotations

import sys

import pytest

from mcp_server.infrastructure import pipeline_install_lock as mod
from mcp_server.infrastructure.pipeline_install_lock import (
    InstallLockBusy,
    install_lock,
)


@pytest.fixture
def lock_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_LOCK_FILE", tmp_path / ".install.lock")
    return tmp_path / ".install.lock"


def test_acquire_and_release_creates_lock_file(lock_in_tmp):
    with install_lock():
        assert lock_in_tmp.exists()
    # Re-acquire after release must succeed (lock was freed).
    with install_lock():
        pass


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX flock contention semantics; NT mandatory locks differ",
)
def test_contended_acquire_raises_busy(lock_in_tmp):
    with install_lock():
        with pytest.raises(InstallLockBusy):
            with install_lock():
                pass
