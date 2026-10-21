"""The census's instruments (test_broker_session_census_repro.py): a
``pg_stat_activity`` sampler and the wait for the session's detached jobs.

source: ADR-1112 acceptance A2, A4
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import psycopg
import pytest

# the store's pools and the broker's start-up migration (pg_session_bounds)
_CORTEX_NAMES = ("cortex-store-", "cortex-migrate-")
# source: the session's background consolidation cycle took 7.6 s in the
# probe of experiment log entry 22; 120 s bounds a slow machine
_JOBS_WAIT_SECONDS = 120
# pid, name, state, ms in its transaction, ms in its state, query head
_ACTIVITY = (
    "SELECT pid, application_name, state,"
    " (extract(epoch FROM now() - xact_start) * 1000)::bigint,"
    " (extract(epoch FROM now() - state_change) * 1000)::bigint, left(query, 80)"
    " FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> %s"
)


class Sampler(threading.Thread):
    def __init__(self, url: str, period: float) -> None:
        super().__init__(daemon=True)
        self.period = period
        self.conn = psycopg.connect(url, autocommit=True)
        self.stop = threading.Event()
        self.owners: set[str] = set()
        self.commands: dict[str, str] = {}
        self.others: set[str] = set()
        self.idle_in_tx = 0
        self.migrations = 0  # samples of the broker's start-up migration
        self.details: list[list] = []  # what an unexpected sample was
        self.idle_outside_broker = 0
        self.max_idle_xact_ms = 0
        self.max_idle_ms = 0
        self.samples = 0
        self.peak = 0

    def run(self) -> None:
        own = self.conn.info.backend_pid
        while not self.stop.is_set():
            rows = self.conn.execute(_ACTIVITY, (own,)).fetchall()
            self.samples += 1
            cortex = [row[1] for row in rows if row[1].startswith(_CORTEX_NAMES)]
            self.peak = max(self.peak, len(cortex))
            for pid in {name.rsplit("-", 1)[1] for name in cortex} - self.owners:
                self.owners.add(pid)  # its command while it is alive
                self.commands[pid] = _command_of(pid)
            self.migrations += sum(1 for n in cortex if n.startswith("cortex-migrate-"))
            for row in rows:
                if not row[1].startswith(_CORTEX_NAMES):
                    self.others.add(row[1])
                    self.details.append(["other", *row])
                if row[2] == "idle in transaction":
                    self._idle(row)
            time.sleep(self.period)
        self.conn.close()

    def _idle(self, row) -> None:
        self.idle_in_tx += 1
        self.details.append(["idle_in_transaction", *row])
        if not row[1].startswith("cortex-store-"):
            self.idle_outside_broker += 1
        self.max_idle_xact_ms = max(self.max_idle_xact_ms, row[3] or 0)
        self.max_idle_ms = max(self.max_idle_ms, row[4] or 0)


def _label(command: str) -> str:
    """A job's module or executable name, never its arguments or paths."""
    words = command.split()
    named = [w for w in words if w.startswith("mcp_server.")]
    return named[0] if named else Path(words[0]).name


def wait_for_session_jobs() -> tuple[float, list[str]]:
    """Wait for every process the session started, detached ones included
    (they carry the test session's token), the private cluster excepted."""
    from tests_py._process_leak_guard import TOKEN_VAR, live_tokened_processes  # noqa: PLC0415

    started = time.monotonic()
    seen: set[str] = set()
    while True:
        jobs = [
            (pid, command)
            for pid, command in live_tokened_processes(os.environ[TOKEN_VAR])
            if not command.startswith("postgres") and "/bin/postgres " not in command
        ]
        seen.update(_label(command) for _, command in jobs)
        if not jobs:
            return round(time.monotonic() - started, 2), sorted(seen)
        if time.monotonic() - started > _JOBS_WAIT_SECONDS:
            for pid, _ in jobs:
                subprocess.run(["kill", str(pid)], check=False)
            pytest.fail(
                f"session jobs alive after {_JOBS_WAIT_SECONDS} s: {sorted(seen)}"
            )
        time.sleep(0.5)


def _command_of(pid: str) -> str:
    done = subprocess.run(
        ["ps", "-o", "command=", "-p", pid], capture_output=True, text=True, check=False
    )
    return done.stdout.strip()
