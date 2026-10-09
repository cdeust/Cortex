"""The hermetic hook env bounds the resident capture worker and waits for it.

source: this PR; contract in tests_py/_hermetic_hook_env.py
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

from mcp_server.infrastructure import capture_socket
from tests_py import _hermetic_hook_env as hermetic

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the capture worker is POSIX-only (ADR-0486)"
)


def test_no_runtime_directory_means_no_worker_and_returns_at_once(
    tmp_path: Path,
) -> None:
    hermetic.await_capture_worker_exit({"CORTEX_CLAUDE_DIR": str(tmp_path)})


@posix_only
def test_waits_for_the_worker_lifetime_lease_then_returns(tmp_path: Path) -> None:
    runtime = capture_socket.runtime_directory(tmp_path)
    held, release, done = threading.Event(), threading.Event(), threading.Event()

    def worker() -> None:
        with capture_socket.lease(runtime / "worker.lock"):
            held.set()
            release.wait()

    thread = threading.Thread(target=worker)
    thread.start()
    held.wait()

    def waiter() -> None:
        hermetic.await_capture_worker_exit({"CORTEX_CLAUDE_DIR": str(tmp_path)})
        done.set()

    blocked = threading.Thread(target=waiter)
    blocked.start()
    assert not done.is_set()  # the lease is held: the wait cannot have returned
    release.set()
    blocked.join()
    thread.join()
    assert done.is_set()


@posix_only
def test_hermetic_env_bounds_the_worker_idle_window_and_embedding_download(
    tmp_path: Path,
) -> None:
    env, _ = hermetic.hermetic_hook_env({"PATH": ""}, tmp_path)
    assert env["CORTEX_CAPTURE_IDLE_SECONDS"] == "1"
    assert env["CORTEX_EMBEDDING_ZERO_DOWNLOAD"] == "1"
