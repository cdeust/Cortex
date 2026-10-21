"""One-command reproduction for the connection-broker study (ADR-1112).

    python scripts/repro_connection_broker.py baseline
    python scripts/repro_connection_broker.py increment0

Each run executes one measurement, then APPENDS one timestamped entry (UTC
time, git HEAD, dirty flag, command, pytest exit code, measured numbers) to
``docs/verification/connection-broker/experiment-log.md``. The log is
append-only: this script never rewrites earlier entries, and a failed run is
recorded like a passing one.

* ``baseline``: the control environment. A private PostgreSQL cluster
  (``max_connections = 20``, same binaries as the developer server, never the
  live store) with one idle transaction, one queued no-op ``ALTER TABLE`` and
  8 hook-like processes, each opening its own ``PgMemoryStore``
  (tests_py/infrastructure/test_pg_connection_saturation_repro.py).
* ``increment0``: the increment-0 guarantees on the throwaway test database
  (tests_py/infrastructure/test_pg_no_runtime_ddl_no_idle_tx.py).
* ``priority``: acceptance A5, a real broker on a private cluster with the
  heavy load sent as background, then as interactive
  (tests_py/infrastructure/test_broker_priority_repro.py).
* ``census``: acceptance A2 and A4, a scripted session of real hook and tool
  processes on a private cluster with a ``pg_stat_activity`` sampler
  (tests_py/infrastructure/test_broker_session_census_repro.py).
* ``saturation``: acceptance A1, the ``baseline`` scenario with 8 and 64
  clients that reach the store through the broker
  (tests_py/infrastructure/test_broker_saturation_repro.py).
* ``latency``: acceptance A6, the benchmark's recall path on the in-process
  store and through the broker
  (tests_py/infrastructure/test_broker_recall_latency_repro.py).
* ``bounds``: the audit's probe A on the store's connections: name and
  session bounds per pool (tests_py/infrastructure/test_pg_session_bounds.py).

The broker's acceptance measurements (ADR-1112 section Acceptance) are
added here by the increments that implement them, never before.

source: ADR-1112
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# source: ADR-1112 repository root, from this file's location
ROOT = Path(__file__).resolve().parents[1]
# source: ADR-1112 the append-only experiment log
LOG = ROOT / "docs" / "verification" / "connection-broker" / "experiment-log.md"
# source: ADR-1112 one measurement per subcommand
TARGETS = {
    "baseline": "tests_py/infrastructure/test_pg_connection_saturation_repro.py",
    "increment0": "tests_py/infrastructure/test_pg_no_runtime_ddl_no_idle_tx.py",
    "priority": "tests_py/infrastructure/test_broker_priority_repro.py",
    "bounds": "tests_py/infrastructure/test_pg_session_bounds.py",
    "census": "tests_py/infrastructure/test_broker_session_census_repro.py",
    "saturation": "tests_py/infrastructure/test_broker_saturation_repro.py",
    "latency": "tests_py/infrastructure/test_broker_recall_latency_repro.py",
}


def _git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def _run(target: str) -> tuple[int, dict, str]:
    with tempfile.TemporaryDirectory() as scratch:
        numbers = Path(scratch) / "measured.json"
        env = dict(os.environ, CORTEX_REPRO_JSON=str(numbers))
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", target],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        measured = json.loads(numbers.read_text()) if numbers.exists() else {}
    tail = done.stdout.strip().splitlines()[-1:] or [""]
    return done.returncode, measured, tail[0]


def _append(name: str, code: int, measured: dict, summary: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dirty = "dirty" if _git("status", "--porcelain") else "clean"
    entry = (
        f"\n### {stamp} {name}\n\n"
        f"- head: `{_git('rev-parse', 'HEAD')}` ({dirty})\n"
        f"- command: `python scripts/repro_connection_broker.py {name}`\n"
        f"- pytest exit code: {code} ({summary})\n"
        f"- measured: `{json.dumps(measured, sort_keys=True)}`\n"
    )
    with LOG.open("a", encoding="utf-8") as log:
        log.write(entry)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("measurement", choices=sorted(TARGETS))
    name = parser.parse_args().measurement
    code, measured, summary = _run(TARGETS[name])
    _append(name, code, measured, summary)
    print(f"{name}: exit {code} ({summary}) {json.dumps(measured, sort_keys=True)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
