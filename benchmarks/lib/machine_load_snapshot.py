"""Machine-load snapshot for a benchmark cell (issue #368 follow-up).

2026-08-10 incident: a 5-cell trust-factor sweep ran while three other
agents' full pytest suites were active on the same machine (load average
~11-14 on a 10-core box); one cell crashed on a native fatal error, and the
crash was the ONLY visible signal — cells that merely finished under the
same contention could have returned degraded numbers (saturated connection
pool, cold cache, GC pressure) with nothing in the artifact to show it. The
whole grid was discarded and re-run rather than salvaged, per this
project's own rule: a measurement from a harness with a known defect is
invalid and is redone, not patched after the fact — and contention is
exactly such a defect. This snapshot is recorded so that rule can be
applied by inspection later, instead of by asking whoever happened to be
watching at the time.

Taken TWICE per cell (same-day follow-up, same incident): once at cell
START (`write_manifest.write_start_snapshot`, called before `start_db` so
it predates the container/DB overhead too) and once at cell END (inside
`write_manifest.build_manifest`). A crash is the visible failure mode; a
cell that merely FINISHES under contention is the invisible one, and a
single end-of-run snapshot cannot distinguish "ran under load throughout"
from "load spiked right at the end". Two points at least bound the window.

Every probe here is best-effort: a failure records `None` rather than
aborting manifest generation, matching every other field `write_manifest.py`
records.
"""

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

    Filtered in Python, not via a shell `grep -c "[p]ytest"` idiom: a
    subprocess.run argv has no shell to bracket-escape a self-match, so the
    filter runs here instead, over the same process list that idiom reads.

    The `COLUMNS` override fixes a real undercount, not just a test flake
    (caught by tests_py/benchmarks/test_write_manifest_machine_load.py's
    own self-referential assertion failing on GitHub's Linux CI runner,
    2026-08-10): both BSD ps (macOS) and GNU procps (Linux) truncate the
    COMMAND column to `$COLUMNS` when stdout is not a terminal and COLUMNS
    is unset, and `ps aux`'s fixed-width USER/PID/... columns alone can
    exceed a default 80-column budget before COMMAND even starts — cutting
    off the "pytest" substring entirely on a long interpreter path.
    """
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


def machine_load_snapshot() -> dict:
    """Load average + concurrent pytest/container counts, as this run saw
    them. See this module's docstring for why."""
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:  # not available on this platform (e.g. Windows)
        load1 = load5 = load15 = None
    return {
        "load_average_1m": load1,
        "load_average_5m": load5,
        "load_average_15m": load15,
        "cpu_count": os.cpu_count(),
        "concurrent_pytest_processes": count_pytest_processes(),
        "concurrent_docker_containers": count_docker_containers(),
    }
