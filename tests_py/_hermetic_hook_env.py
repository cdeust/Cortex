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
``await_capture_worker_exit`` blocks on the worker's own lifetime lease, the
kernel ``flock`` it holds until it exits, so no sleep or poll decides anything.

source: this PR; spawn sites mcp_server/hooks/session_start.py
(_maybe_background_reanalyze, _maybe_background_consolidate)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from mcp_server.infrastructure import capture_socket
from mcp_server.infrastructure.upstream_identity import BINARY_NAMES

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


def await_capture_worker_exit(env: dict[str, str]) -> None:
    """Block until no resident capture worker serves ``env``'s Claude dir.

    postcondition: the worker's lifetime lease (``worker.lock``) was acquired,
    i.e. the worker, if one was started, has exited; raises on the deadline.
    """
    runtime = Path(env["CORTEX_CLAUDE_DIR"]) / ".capture-worker"
    if not runtime.is_dir():
        return  # no capture was admitted, so nothing was spawned
    deadline = time.monotonic() + _WORKER_EXIT_DEADLINE_SECONDS
    with capture_socket.lease(runtime / "worker.lock", deadline):
        pass
