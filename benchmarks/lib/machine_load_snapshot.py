"""Machine-load snapshot for a benchmark cell.

Taken TWICE per cell (same-day follow-up, same incident): once at cell
START (`write_manifest.write_start_snapshot`, called before `start_db` so
it predates the container/DB overhead too) and once at cell END (inside
`write_manifest.build_manifest`). A crash is the visible failure mode; a
cell that merely FINISHES under contention is the invisible one, and a
single end-of-run snapshot cannot distinguish "ran under load throughout"
from "load spiked right at the end". Two points at least bound the window.

source: ADR-0080"""

from __future__ import annotations

import os
import subprocess


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> str | None:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, check=False, env=env
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def count_pytest_processes() -> int | None:
    """Concurrent `pytest` processes system-wide, or None if unreadable.

    source: ADR-0080"""
    ps_out = _run(["ps", "aux"], env={**os.environ, "COLUMNS": "1000"})
    if ps_out is None:
        return None
    return sum(
        1 for line in ps_out.splitlines() if "pytest" in line and "grep" not in line
    )


def count_docker_containers() -> int | None:
    """Concurrent running Docker containers, or None if unreadable."""
    docker_out = _run(["docker", "ps", "-q"])
    if docker_out is None:
        return None
    return len([line for line in docker_out.splitlines() if line.strip()])


def _load_averages() -> tuple[float | None, float | None, float | None]:
    """1/5/15-minute load averages, or three None where the OS reports none.

    ``os.getloadavg`` is Unix-only: on Windows the attribute does not exist,
    so the lookup raises AttributeError, not OSError (issue #692 class 4).
    On Unix it raises OSError when the value is unobtainable.
    source: CPython 3.12 docs, os.getloadavg (Availability: Unix)"""
    getloadavg = getattr(os, "getloadavg", None)
    if getloadavg is None:
        return None, None, None
    try:
        return getloadavg()
    except OSError:
        return None, None, None


def machine_load_snapshot() -> dict:
    """Load average + concurrent pytest/container counts, as this run saw
        them.

    source: ADR-0080"""
    load1, load5, load15 = _load_averages()
    return {
        "load_average_1m": load1,
        "load_average_5m": load5,
        "load_average_15m": load15,
        "cpu_count": os.cpu_count(),
        "concurrent_pytest_processes": count_pytest_processes(),
        "concurrent_docker_containers": count_docker_containers(),
    }
