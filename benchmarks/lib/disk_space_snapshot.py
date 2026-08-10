"""Disk-space snapshot for a benchmark cell (issue #368 follow-up).

2026-08-10 incident (reported by a neighboring session sharing this
machine): leaked throwaway SQLite test databases (226-357 MB per run)
filled the host disk to 100% on 2026-08-09 — PostgreSQL went down and even
the Bash tool could no longer write its own output file. A cell can finish
cleanly and still return degraded numbers because the volume filled under
it, and that leaves no more trace in the artifact than CPU contention does
(see `machine_load_snapshot.py`'s docstring — this is the same failure
shape, a different resource). Recorded the same way and for the same
reason: best-effort, taken at cell start and cell end, never aborts
manifest generation.

Two paths are measured, both best-effort:
  - the repo root's filesystem — where benchmark datasets, throwaway test
    databases, and HuggingFace cache actually land;
  - Docker's storage root (`docker info`'s `DockerRootDir`) — under a VM
    backend (colima, Docker Desktop) this is a guest-internal path and
    `shutil.disk_usage` on it measures the HOST filesystem backing the VM
    image file, not a second independent volume; when it resolves to the
    same filesystem as the repo root this is redundant but harmless, and
    when Docker is unreachable it is simply `None`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _usage(path: str) -> dict | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {
        "path": path,
        "free_bytes": usage.free,
        "total_bytes": usage.total,
    }


def _docker_root_dir() -> str | None:
    try:
        out = subprocess.run(
            ["docker", "info", "--format", "{{.DockerRootDir}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def disk_space_snapshot() -> dict:
    """Free/total bytes on the volume(s) backing benchmark data + Docker
    storage, as this run saw them. See this module's docstring for why."""
    docker_root = _docker_root_dir()
    return {
        "repo_root": _usage(str(_REPO_ROOT)),
        "docker_root": _usage(docker_root) if docker_root else None,
    }
