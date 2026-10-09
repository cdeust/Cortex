"""Environment under which a real SessionStart hook subprocess starts no
detached background worker, so a test that drives it leaves no process behind.

SessionStart (``session_start.main``) spawns two detached workers
(``start_new_session=True``, reparented to pid 1 when the hook exits):
``ingest_codebase_background`` from ``_maybe_background_reanalyze`` and
``consolidate_background`` from ``_maybe_background_consolidate``. Each is
isolated here through the production contract, never a test-only branch:

* ingest: ``CORTEX_AUTO_INSTALL_PIPELINE=0`` stops the installer from
  downloading the prebuilt pipeline binary into the temp HOME (the cause of
  the tests_py/hooks/test_entry.py leak: discovery then finds it); the
  scrubbed PATH hides any host install; a temp HOME hides the host's
  marketplace install (``installed_plugins.json``); the cwd is a temp
  project, never this repository, so nothing resolves
  ``../ai-architect-mcp-codebase`` or ingests the repo.
  ``discover_pipeline_command()`` returns None and the hook returns.
* consolidate: the coordinator's public ``ensure_cycle`` records a cycle as
  just run (a ``spawn_fn`` that starts nothing), so the hook sees
  ``skipped_fresh`` for the 6 h period.

A third worker is the resident capture worker (ADR-0486, ADR-0508): a real
PostToolUse hook run admits its capture to a worker that, by design, outlives
the hook and exits only after ``CORTEX_CAPTURE_IDLE_SECONDS`` without traffic
(default 300 s). It is started on Linux only: on macOS the temp directory sits
under the ``/var`` symlink, which the worker's directory check refuses, so the
capture is skipped before any spawn (measured 2026-10-09). The hermetic env sets
the idle window to one second (the production variable), and
``await_capture_worker_exit`` blocks until the worker PROCESS has exited: first
on its lifetime lease (the kernel ``flock``, released by ``capture_worker.main``
before the interpreter shuts down, so the lease alone is NOT proof of exit),
then on the process itself through the kernel (Linux ``pidfd_open``, macOS
``kqueue`` with ``NOTE_EXIT``). The pid comes from the leak guard's own token
listing, because the hook starts the worker detached, so no handle exists. No
sleep or poll decides anything.

source: this PR; spawn sites mcp_server/hooks/session_start.py
(_maybe_background_reanalyze, _maybe_background_consolidate)
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

from mcp_server.infrastructure import capture_socket
from mcp_server.infrastructure.upstream_identity import BINARY_NAMES
from tests_py._process_leak_guard import TOKEN_VAR, live_tokened_processes

REPO_ROOT = Path(__file__).resolve().parents[1]
# The names pipeline_discovery looks up on PATH: "cortex-pipeline" plus
# upstream_identity.BINARY_NAMES (pipeline_discovery._BINARY_CANDIDATES).
_PIPELINE_BINARIES = ("cortex-pipeline", *BINARY_NAMES)


def _path_without_pipeline_binaries(path: str) -> str:
    """``path`` minus every directory that holds a pipeline binary, so
    ``shutil.which`` inside the hook finds none whatever the host installed."""
    kept = [
        d
        for d in path.split(os.pathsep)
        if not any(os.access(os.path.join(d, b), os.X_OK) for b in _PIPELINE_BINARIES)
    ]
    return os.pathsep.join(kept)


_SEED_CONSOLIDATE_STAMP = (
    "from mcp_server.infrastructure.groomer_coordinator import "
    "GroomerCoordinator, resolve_store_key; "
    "GroomerCoordinator(resolve_store_key()).ensure_cycle("
    "period_hours=6, spawn_fn=lambda: None)"
)


def hermetic_hook_env(
    base: dict[str, str], tmp_path: Path
) -> tuple[dict[str, str], Path]:
    """Return ``(env, project)``: ``base`` made hermetic as the module
    docstring describes, and a temp project directory to use as the cwd.

    postcondition: a consolidate cycle is recorded as just run in the
    coordinator state under ``tmp_path/home``.
    """
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = dict(base)
    env["HOME"] = str(home)
    env["CORTEX_AUTO_INSTALL_PIPELINE"] = "0"
    # source: ADR-0489 (capture worker idle window), ADR-0519 (embedding opt-out)
    env["CORTEX_CAPTURE_IDLE_SECONDS"] = "1"
    env["CORTEX_EMBEDDING_ZERO_DOWNLOAD"] = "1"
    env["PATH"] = _path_without_pipeline_binaries(env.get("PATH", ""))
    env["PYTHONPATH"] = str(REPO_ROOT)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    subprocess.run(
        [sys.executable, "-c", _SEED_CONSOLIDATE_STAMP],
        env=env,
        cwd=project,
        check=True,
        capture_output=True,
    )
    return env, project


# source: ADR-0489 -- the worker polls its shutdown flag at min(transport, idle)
# seconds and the idle window is one second here; 30 s is a deadline, not a delay.
_WORKER_EXIT_DEADLINE_SECONDS = 30.0


# source: mcp_server/hooks/capture_worker.py -- the module the hook starts detached
_WORKER_MODULE = "mcp_server.hooks.capture_worker"


def wait_for_process_exit(pid: int, deadline: float) -> None:
    """Block until process ``pid`` has exited, through the kernel, not a poll.

    postcondition: returns when ``pid`` is gone (also when it was already gone
    at registration); raises ``TimeoutError`` at the ``time.monotonic()``
    ``deadline``. Linux: ``os.pidfd_open`` readable on exit. macOS/BSD:
    ``kqueue`` ``KQ_NOTE_EXIT``. Windows has no capture worker (ADR-0486).

    source: pidfd_open(2); kqueue(2) EVFILT_PROC NOTE_EXIT"""
    timeout = max(0.0, deadline - time.monotonic())
    if sys.platform.startswith("linux"):
        try:
            handle = os.pidfd_open(pid)
        except ProcessLookupError:
            return
        try:
            ready, _, _ = select.select([handle], [], [], timeout)
        finally:
            os.close(handle)
        if not ready:
            raise TimeoutError(f"process {pid} still alive after the deadline")
        return
    queue = select.kqueue()
    try:
        watch = select.kevent(
            pid,
            select.KQ_FILTER_PROC,
            select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
            select.KQ_NOTE_EXIT,
        )
        try:
            events = queue.control([watch], 1, timeout)
        except ProcessLookupError:
            return
        if not events:
            raise TimeoutError(f"process {pid} still alive after the deadline")
    finally:
        queue.close()


def await_capture_worker_exit(env: dict[str, str]) -> None:
    """Block until no resident capture worker serves ``env``'s Claude dir.

    postcondition: the worker's lifetime lease (``worker.lock``) was acquired
    AND every capture worker process of this test session has exited (the lease
    is released before the interpreter finishes shutting down); raises
    ``TimeoutError`` on the shared deadline.
    """
    runtime = Path(env["CORTEX_CLAUDE_DIR"]) / ".capture-worker"
    if not runtime.is_dir():
        return  # no capture was admitted, so nothing was spawned
    deadline = time.monotonic() + _WORKER_EXIT_DEADLINE_SECONDS
    with capture_socket.lease(runtime / "worker.lock", deadline):
        pass
    for pid, command in live_tokened_processes(os.environ[TOKEN_VAR]):
        if _WORKER_MODULE in command:
            wait_for_process_exit(pid, deadline)
