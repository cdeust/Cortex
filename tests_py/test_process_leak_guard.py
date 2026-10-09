"""The leak guard sees a detached, re-parented process and ignores the rest.

source: this PR; contract in tests_py/_process_leak_guard.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from unittest import mock

from tests_py import _process_leak_guard as guard
from tests_py._process_leak_guard import (
    TOKEN_VAR,
    fail_on_leaks,
    live_tokened_processes,
    parse_process_table,
)

posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="the guard reads process environments through ps; no Windows equivalent",
)

# The child blocks on its own stdin until the test closes it: no sleep, and
# the test ends the child by closing the pipe, then waits on the handle.
_BLOCK_ON_STDIN = "import sys; sys.stdin.read()"


def _spawn(env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(  # noqa: S603 — fixed argv
        [sys.executable, "-c", _BLOCK_ON_STDIN],
        stdin=subprocess.PIPE,
        start_new_session=True,
        env=env,
    )


def _finish(child: subprocess.Popen) -> None:
    assert child.stdin is not None
    child.stdin.close()
    child.wait()


@posix_only
def test_detached_child_carrying_the_token_is_reported_then_gone() -> None:
    token = os.environ[TOKEN_VAR]
    child = _spawn(dict(os.environ))
    try:
        assert child.pid in [pid for pid, _ in live_tokened_processes(token)]
    finally:
        _finish(child)
    assert child.pid not in [pid for pid, _ in live_tokened_processes(token)]


@posix_only
def test_child_without_the_token_is_not_reported() -> None:
    env = {k: v for k, v in os.environ.items() if k != TOKEN_VAR}
    child = _spawn(env)
    try:
        assert child.pid not in [
            pid for pid, _ in live_tokened_processes(os.environ[TOKEN_VAR])
        ]
    finally:
        _finish(child)


@posix_only
def test_pytest_itself_is_never_reported() -> None:
    assert os.getpid() not in [
        pid for pid, _ in live_tokened_processes(os.environ[TOKEN_VAR])
    ]


_TOKEN = "tok"
_ENV = f"{TOKEN_VAR}={_TOKEN}"


def test_resource_tracker_is_exempt_only_as_a_direct_child() -> None:
    tracker = "python -c from multiprocessing.resource_tracker import main"
    me = os.getpid()
    table = f"900 {me} {tracker} {_ENV}\n901 1 {tracker} {_ENV}\n"
    assert [pid for pid, _ in parse_process_table(table, _TOKEN, ())] == [901]


def test_malformed_lines_are_skipped_not_reported() -> None:
    table = f"  PID  PPID COMMAND\nnot a row {_ENV}\n7 1\n902 1 worker {_ENV}\n"
    assert parse_process_table(table, _TOKEN, ()) == [(902, "worker")]


def test_own_pids_and_other_tokens_are_excluded() -> None:
    table = f"5 1 a {_ENV}\n6 1 b {TOKEN_VAR}=other\n"
    assert parse_process_table(table, _TOKEN, (5,)) == []


@posix_only
def test_a_leaked_child_makes_the_teardown_fail() -> None:
    child = _spawn(dict(os.environ))
    try:
        with pytest.raises(pytest.fail.Exception, match="still alive at teardown"):
            fail_on_leaks(os.environ[TOKEN_VAR])
    finally:
        _finish(child)
    fail_on_leaks(os.environ[TOKEN_VAR])  # clean once the child is waited on


@posix_only
def test_ps_failure_raises_instead_of_passing_silently() -> None:
    failing = [sys.executable, "-c", "import sys; sys.exit(3)"]
    real = subprocess.Popen

    def fake(argv, **kw):
        return real(failing, **kw)

    with mock.patch.object(guard.subprocess, "Popen", fake):
        with pytest.raises(RuntimeError, match="cannot read the process table"):
            live_tokened_processes(_TOKEN)


def test_windows_is_inactive_and_says_so() -> None:
    with mock.patch.object(guard.sys, "platform", "win32"):
        with pytest.warns(UserWarning, match="inactive on Windows"):
            assert live_tokened_processes(_TOKEN) == []
