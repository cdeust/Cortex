"""Tests for shared.subprocess_safe.run_with_hard_timeout — the #94 fix.

``subprocess.run``/``check_output`` with ``timeout=`` used to be the
remaining high-risk call sites reachable from live MCP tool handlers
(``handlers/auto_task_record_writer.py::_git_commits_in_window`` and
``handlers/validate_memory.py``; a third, ``git_diff_exec.py::git_cmd_safe``,
went away with the unwired git-diff module in #196). On Windows, CPython's
own ``TimeoutExpired`` handling inside ``subprocess.run`` calls
``Popen.communicate()`` a *second* time with no deadline, which can hang
forever if a concurrent sibling process inherited the pipe's write handle
(cdeust/Cortex#91/#94). ``run_with_hard_timeout`` replaces both call sites
with an open-coded ``Popen`` + single bounded ``communicate()`` + kill —
never calling ``communicate()`` a second time.

These tests verify: (1) nominal success/failure behavior is unchanged
from the ``subprocess.run``-based originals, and (2) the no-second-
communicate() contract, using a fake ``Popen`` that raises if called
twice — since the real Windows deadlock isn't reproducible on macOS/
Linux CI, this is the closest verifiable proxy for "the trap can't fire".
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from mcp_server.shared import subprocess_safe as ss
from mcp_server.shared.subprocess_safe import run_with_hard_timeout

# ── Nominal behavior (real subprocess, unchanged from subprocess.run) ──


def test_returns_stripped_stdout_on_success():
    out = run_with_hard_timeout([sys.executable, "-c", "print('hello')"], timeout=5)
    assert out == "hello"


def test_returns_empty_string_for_successful_command_with_no_output():
    out = run_with_hard_timeout([sys.executable, "-c", "pass"], timeout=5)
    assert out == ""


def test_returns_none_on_nonzero_exit():
    out = run_with_hard_timeout(
        [sys.executable, "-c", "import sys; sys.exit(1)"], timeout=5
    )
    assert out is None


def test_returns_none_when_binary_does_not_exist():
    out = run_with_hard_timeout(["/no/such/binary-xyz-cortex-94"], timeout=1)
    assert out is None


def test_returns_none_on_real_timeout_without_hanging():
    # The actual regression this exists to prevent: a slow child must be
    # killed and the function must return promptly — not block for the
    # child's full runtime (2s) nor forever.
    start = time.monotonic()
    out = run_with_hard_timeout(
        [sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.2
    )
    elapsed = time.monotonic() - start
    assert out is None
    assert elapsed < 1.5, f"took {elapsed}s — the timeout path is not bounded"


def test_encoding_parameter_is_honored():
    out = run_with_hard_timeout(
        [sys.executable, "-c", "print('café')"], timeout=5, encoding="utf-8"
    )
    assert out == "café"


# ── #94 contract: never call communicate() a second time after kill() ──


class _FakeProcessTimesOutOnce:
    """Simulates the Windows deadlock trap's precondition and proves the
    fix never re-triggers it: a second ``communicate()`` call raises
    ``AssertionError`` instead of hanging, so the test fails loudly (not
    by timing out the test suite) if the guarantee regresses.
    """

    def __init__(self, *_a, **_kw):
        self.communicate_calls = 0
        self.killed = False
        self.waited = False

    def communicate(self, timeout=None):
        self.communicate_calls += 1
        if self.communicate_calls > 1:
            raise AssertionError(
                "communicate() called a second time after kill() — "
                "this is the exact Windows pipe-handle deadlock trap "
                "(cdeust/Cortex#91/#94) that run_with_hard_timeout must "
                "never reintroduce."
            )
        raise subprocess.TimeoutExpired(cmd="fake-git", timeout=timeout)

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_timeout_kills_and_never_recalls_communicate(monkeypatch):
    fake = _FakeProcessTimesOutOnce()
    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **kw: fake)

    out = run_with_hard_timeout(["git", "log"], timeout=10)

    assert out is None
    assert fake.killed is True
    assert fake.communicate_calls == 1
    assert fake.waited is True


class _FakeProcessWaitAlsoTimesOut:
    """Even if the post-kill reap itself can't complete quickly, the
    function must not raise or hang — it abandons the zombie and returns
    the degraded result.
    """

    def __init__(self, *_a, **_kw):
        self.killed = False

    def communicate(self, timeout=None):
        raise subprocess.TimeoutExpired(cmd="fake-git", timeout=timeout)

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired(cmd="fake-git", timeout=timeout)


def test_timeout_survives_a_reap_that_also_times_out(monkeypatch):
    fake = _FakeProcessWaitAlsoTimesOut()
    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **kw: fake)

    out = run_with_hard_timeout(["git", "log"], timeout=10)

    assert out is None
    assert fake.killed is True


def test_spawn_failure_returns_none_without_touching_communicate(monkeypatch):
    def _boom(*_a, **_kw):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(ss.subprocess, "Popen", _boom)
    assert run_with_hard_timeout(["git", "log"], timeout=10) is None


@pytest.mark.parametrize("exc_cls", [OSError, FileNotFoundError])
def test_spawn_failure_variants_return_none(monkeypatch, exc_cls):
    def _boom(*_a, **_kw):
        raise exc_cls("boom")

    monkeypatch.setattr(ss.subprocess, "Popen", _boom)
    assert run_with_hard_timeout(["git", "log"], timeout=10) is None
