"""Semantic search arrives in the background, never inside a hook — stdlib only.

The ML set (sentence-transformers, torch: about 1 GB) and the pinned embedding
model take minutes on a first install; Claude Code cancels the SessionStart
hook at its 30 s timeout and discards its output, and the MCP server must
answer ``initialize`` within the host's startup timeout. So the SessionStart
launch installs only the base set and starts ONE detached job that installs
the ML set from uv.lock and downloads the model; until it finishes, recall is
keyword-only and the SessionStart message says so.

The job is ``launcher.py mcp_server.embedding_warmup``: the launcher installs
base + ML for that module, then the module downloads the model. A job lock
held for the job's life makes a second start a no-op; the OS releases it if
the job dies, so a killed job is restarted by the next session.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import launcher_deps
import launcher_lock

WARMUP_MODULE = "mcp_server.infrastructure.embedding_warmup"  # source: ADR-1104
# The job writes its outcome here; the launcher hands it to the SessionStart
# hook. source: ADR-1104
STATUS_ENV = "CORTEX_SEMANTIC_STATUS_FILE"


def job_lock(deps_dir: str) -> str:
    """The lock the running job holds: beside ``deps_dir``, in plugin data."""
    return f"{deps_dir}.semantic-job.lock"


def job_log(deps_dir: str) -> Path:
    """Where the job's output goes: the first place to look when it fails."""
    return Path(deps_dir).parent / "semantic-install.log"


def status_file(deps_dir: str) -> Path:
    """The job's outcome: ``{"status": "ready"}`` or ``{"status": "failed", ...}``."""
    return Path(deps_dir).parent / "semantic-install.json"


def state(deps_dir: str) -> tuple[str, str]:
    """``("ready", "")``, ``("failed", why)`` or ``("installing", "")``.

    Ready needs both the ML set stamped for this uv.lock and the job's own
    success record (the model is downloaded after the set installs).
    """
    try:
        outcome = json.loads(status_file(deps_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        outcome = {}
    if outcome.get("status") == "failed":
        return "failed", f"{outcome.get('error', 'unknown error')} (log: {job_log(deps_dir)})"
    if outcome.get("status") == "ready" and launcher_deps.ml_ready(deps_dir):
        return "ready", ""
    return "installing", ""


def _detached() -> dict:
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        return {"creationflags": flags}
    return {"start_new_session": True}


def start(deps_dir: str, launcher: str) -> tuple[str, str]:
    """Start the job unless semantic search is ready or the job runs.

    Returns ``state()`` as it stands once the job is started. Never waits for
    the job. A failed job is started again: a network failure is transient.
    """
    current = state(deps_dir)
    if current[0] == "ready":
        return current
    with launcher_lock.held_if_free(job_lock(deps_dir)) as free:
        if not free:
            return current  # the job is already running
    log = job_log(deps_dir)
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env[STATUS_ENV] = str(status_file(deps_dir))
    with log.open("ab") as sink:
        subprocess.Popen(
            [sys.executable, launcher, WARMUP_MODULE],
            stdin=subprocess.DEVNULL,
            stdout=sink,
            stderr=sink,
            env=env,
            **_detached(),
        )
    return current


def _write_status(deps_dir: str, outcome: dict) -> None:
    status_file(deps_dir).write_text(json.dumps(outcome), encoding="utf-8")


def run_job(deps_dir: str, install, run) -> None:
    """The job's body: hold the job lock, ``install()`` the sets, ``run()`` warm-up.

    A second job finds the lock held and returns at once. ``run`` records
    the outcome in the status file (``STATUS_ENV``); this marks the attempt.
    """
    with launcher_lock.held_if_free(job_lock(deps_dir)) as mine:
        if not mine:
            print("[cortex-launcher] semantic search install already running", file=sys.stderr)
            return
        _write_status(deps_dir, {"status": "installing", "pid": os.getpid()})
        os.environ[STATUS_ENV] = str(status_file(deps_dir))
        install()
        run()
