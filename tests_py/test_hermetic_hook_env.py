"""The hermetic hook env bounds the resident capture worker and waits for it.

source: this PR; contract in tests_py/_hermetic_hook_env.py
"""

from __future__ import annotations

import ctypes
import errno
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcp_server.infrastructure import capture_socket
from tests_py import _hermetic_hook_env as hermetic

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the capture worker is POSIX-only (ADR-0486)"
)


@pytest.fixture(params=[False, True], ids=["platform-api", "without-os-pidfd"])
def process_wait_backend(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux exercises libc with a real process even if Python has pidfd_open.

    macOS still exercises kqueue; these runs do not claim Linux kernel evidence.
    """
    if request.param:
        monkeypatch.delattr(os, "pidfd_open", raising=False)


def test_linux_pidfd_prefers_the_python_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = Mock(return_value=object())
    loader = Mock(side_effect=AssertionError("libc should not be loaded"))
    monkeypatch.setattr(os, "pidfd_open", native, raising=False)
    monkeypatch.setattr(ctypes, "CDLL", loader)
    assert hermetic._open_linux_pidfd(os.getpid()) is native.return_value
    native.assert_called_once_with(os.getpid())


def test_linux_pidfd_libc_binding_keeps_the_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_fd, write_fd = os.pipe()
    native = Mock(return_value=read_fd)
    loader = Mock(return_value=SimpleNamespace(pidfd_open=native))
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.setattr(ctypes, "CDLL", loader)
    try:
        assert hermetic._open_linux_pidfd(os.getpid()) == read_fd
        loader.assert_called_once_with(None, use_errno=True)
        native.assert_called_once_with(os.getpid(), 0)
        assert native.argtypes == (ctypes.c_int, ctypes.c_uint)
        assert native.restype is ctypes.c_int
        os.fstat(read_fd)  # ownership stays with the caller until its wait ends
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("code", [errno.ESRCH, errno.EPERM, errno.EMFILE])
def test_linux_pidfd_libc_preserves_errors(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    def failed_open(pid: int, flags: int) -> int:
        ctypes.set_errno(code)
        return -1

    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.setattr(
        ctypes, "CDLL", Mock(return_value=SimpleNamespace(pidfd_open=failed_open))
    )
    with pytest.raises(OSError) as raised:
        hermetic._open_linux_pidfd(os.getpid())
    assert raised.value.errno == code
    if code == errno.ESRCH:
        assert isinstance(raised.value, ProcessLookupError)


def test_linux_pidfd_missing_libc_symbol_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.setattr(ctypes, "CDLL", Mock(return_value=SimpleNamespace()))
    with pytest.raises(RuntimeError, match="requires os.pidfd_open or libc.pidfd_open"):
        hermetic._open_linux_pidfd(os.getpid())


def test_no_runtime_directory_means_no_worker_and_returns_at_once(
    tmp_path: Path,
) -> None:
    hermetic.await_capture_worker_exit({"CORTEX_CLAUDE_DIR": str(tmp_path)})


# A real stand-in for the capture worker. ps prints one process per line only
# when the command is one line, so the script is a single line; its argv names the
# worker module (the wait finds the process by that through the leak guard's token
# listing). It holds the lifetime lease, releases it on "release", and lingers
# until stdin closes.
_STAND_IN = (
    "import fcntl, os, sys; "
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600); "
    "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); "
    "sys.stdin.readline(); os.close(fd); print('released', flush=True); "
    "sys.stdin.read()"
)


@pytest.fixture
def stand_in(tmp_path: Path):
    runtime = capture_socket.runtime_directory(tmp_path)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _STAND_IN,
            str(runtime / "worker.lock"),
            "mcp_server.hooks.capture_worker",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout.readline().strip() == "held"
    try:
        yield child
    finally:
        child.stdin.close()
        child.wait(timeout=30)
        child.stdout.close()


def _run_wait(
    tmp_path: Path, patch: pytest.MonkeyPatch
) -> tuple[threading.Thread, threading.Event, threading.Event, list[str]]:
    """Start ``await_capture_worker_exit`` in a thread; return it, its done
    event, an event set once it has listed the live workers, and the errors it
    raised. Closing the stand-in's stdin only after ``listed`` guarantees the
    wait saw a live process, so no timing decides the test."""
    done, listed, errors = threading.Event(), threading.Event(), []
    real_list = hermetic.live_tokened_processes

    def listing(token: str) -> list[tuple[int, str]]:
        found = real_list(token)
        listed.set()
        return found

    patch.setattr(hermetic, "live_tokened_processes", listing)

    def waiter() -> None:
        try:
            hermetic.await_capture_worker_exit({"CORTEX_CLAUDE_DIR": str(tmp_path)})
        except BaseException as exc:  # noqa: BLE001 — handed to the test thread
            errors.append(repr(exc))
        done.set()

    thread = threading.Thread(target=waiter)
    thread.start()
    return thread, done, listed, errors


def _release(stand_in: subprocess.Popen) -> None:
    """Make the stand-in drop its lease while it stays alive."""
    stand_in.stdin.write("release\n")
    stand_in.stdin.flush()
    assert stand_in.stdout.readline().strip() == "released"


@posix_only
@pytest.mark.usefixtures("process_wait_backend")
def test_wait_outlasts_the_released_lease_until_the_process_exits(
    tmp_path: Path, stand_in: subprocess.Popen
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        thread, done, listed, errors = _run_wait(tmp_path, patch)
        _release(stand_in)
        assert listed.wait(timeout=30)  # the lease is free, the process alive
        # A wait that ends on the lease (the defect of d1f1a002) has returned
        # by now. A correct wait cannot, so this bounded negative check never
        # fails a correct implementation.
        assert not done.wait(timeout=0.5)
        stand_in.stdin.close()  # the stand-in can only exit after this line
        thread.join()
    assert done.is_set() and errors == []


@posix_only
@pytest.mark.usefixtures("process_wait_backend")
def test_wait_returns_only_after_the_worker_has_exited(
    tmp_path: Path, stand_in: subprocess.Popen
) -> None:
    closed = threading.Event()
    closed_at_return: list[bool] = []
    real_wait = hermetic.wait_for_process_exit

    def recording(pid: int, deadline: float) -> None:
        real_wait(pid, deadline)
        closed_at_return.append(closed.is_set())

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(hermetic, "wait_for_process_exit", recording)
        thread, _, listed, errors = _run_wait(tmp_path, patch)
        _release(stand_in)
        assert listed.wait(timeout=30)
        closed.set()
        stand_in.stdin.close()
        thread.join()
    assert errors == [] and closed_at_return == [True]


@posix_only
def test_deadline_raises_timeout_while_the_lease_is_held(
    tmp_path: Path, stand_in: subprocess.Popen
) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(hermetic, "_WORKER_EXIT_DEADLINE_SECONDS", 0.5)
        thread, _, _, errors = _run_wait(tmp_path, patch)
        thread.join()
    assert len(errors) == 1 and "TimeoutError" in errors[0]


@posix_only
@pytest.mark.usefixtures("process_wait_backend")
def test_deadline_raises_timeout_while_the_process_lingers(
    tmp_path: Path, stand_in: subprocess.Popen
) -> None:
    _release(stand_in)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(hermetic, "_WORKER_EXIT_DEADLINE_SECONDS", 0.5)
        thread, _, _, errors = _run_wait(tmp_path, patch)
        thread.join()
    assert len(errors) == 1 and "TimeoutError" in errors[0]


@posix_only
@pytest.mark.usefixtures("process_wait_backend")
def test_wait_for_process_exit_returns_at_once_for_a_gone_process() -> None:
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    hermetic.wait_for_process_exit(done.pid, time.monotonic() + 5)


@posix_only
def test_hermetic_env_bounds_the_worker_idle_window_and_embedding_download(
    tmp_path: Path,
) -> None:
    env, _ = hermetic.hermetic_hook_env({"PATH": ""}, tmp_path)
    assert env["CORTEX_CAPTURE_IDLE_SECONDS"] == "1"
    assert env["CORTEX_EMBEDDING_ZERO_DOWNLOAD"] == "1"
