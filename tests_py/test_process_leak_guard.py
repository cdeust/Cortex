"""The leak guard sees a detached, re-parented process and ignores the rest.

source: this PR; contract in tests_py/_process_leak_guard.py
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests_py._process_leak_guard import TOKEN_VAR, live_tokened_processes

pytestmark = pytest.mark.skipif(
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


def test_detached_child_carrying_the_token_is_reported_then_gone() -> None:
    token = os.environ[TOKEN_VAR]
    child = _spawn(dict(os.environ))
    try:
        assert child.pid in [pid for pid, _ in live_tokened_processes(token)]
    finally:
        _finish(child)
    assert child.pid not in [pid for pid, _ in live_tokened_processes(token)]


def test_child_without_the_token_is_not_reported() -> None:
    env = {k: v for k, v in os.environ.items() if k != TOKEN_VAR}
    child = _spawn(env)
    try:
        assert child.pid not in [
            pid for pid, _ in live_tokened_processes(os.environ[TOKEN_VAR])
        ]
    finally:
        _finish(child)


def test_pytest_itself_is_never_reported() -> None:
    assert os.getpid() not in [
        pid for pid, _ in live_tokened_processes(os.environ[TOKEN_VAR])
    ]
