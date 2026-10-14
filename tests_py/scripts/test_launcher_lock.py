"""scripts/launcher_lock.py: an install lock is waited on, never stolen or skipped.

The lock it replaces (ADR-0747's directory lock) let a waiter proceed
unlocked after 30 s while the holder was still installing, so the
SessionStart hook and the MCP server could install into one directory at
once on a first launch. These tests hold the lock from another process.

source: ADR-1104
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
import launcher_lock
with launcher_lock.held(sys.argv[2], 5):
    print("held", flush=True)
    time.sleep(60)
"""


@pytest.fixture
def lock_mod():
    spec = importlib.util.spec_from_file_location(
        "scripts.launcher_lock", REPO_ROOT / "scripts" / "launcher_lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def holder(tmp_path: Path):
    """Another process holding the lock until the test kills it."""
    path = str(tmp_path / "deps.install.lock")
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(REPO_ROOT / "scripts"), path],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
    yield proc, path
    proc.kill()
    proc.wait()


def test_a_held_lock_is_waited_on_then_reported_never_skipped(lock_mod, holder):
    _, path = holder
    with pytest.raises(lock_mod.LockTimeoutError, match="still held"):
        with lock_mod.held(path, 0.5):
            pytest.fail("entered a lock another process holds")


def test_the_lock_is_free_as_soon_as_its_holder_dies(lock_mod, holder):
    proc, path = holder
    proc.kill()
    proc.wait()
    with lock_mod.held(path, 5):
        pass


def test_held_if_free_reports_a_running_holder(lock_mod, holder):
    _, path = holder
    with lock_mod.held_if_free(path) as mine:
        assert mine is False


def test_held_if_free_holds_a_free_lock(lock_mod, tmp_path: Path):
    path = str(tmp_path / "job.lock")
    with lock_mod.held_if_free(path) as mine:
        assert mine is True
        with lock_mod.held_if_free(path) as second:
            assert second is False  # a second descriptor in this process too


def test_waiting_ends_when_the_holder_did_the_work(lock_mod, holder):
    """The MCP server waits for the base set, not for the ML install after it."""
    _, path = holder
    with lock_mod.held_unless(path, 30, lambda: True) as held:
        assert held is False
