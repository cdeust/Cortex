"""Experiments of scripts/repro_lock_chain.py (one variable each: the tree).

Server-side capture only: ``pg_stat_activity`` + ``pg_blocking_pids`` and
``pg_locks`` on ``memories``; DDL counted from the server's own statement
log. Every wait is bounded (harness only) and every outcome is recorded,
including the ones that do not resolve.

source: ADR-1112
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg

# source: ADR-1112 the no-op migration of pg_schema.MIGRATIONS_DDL (ADR-1083)
NOOP_ALTER = (
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS "
    "is_team_decision BOOLEAN NOT NULL DEFAULT FALSE"
)
# source: ADR-1112 harness bound for any single wait (never a product timeout)
WAIT_S = 15.0
# source: PostgreSQL deadlock_timeout default 1 s; three detection rounds
DEADLOCK_WINDOW_S = 3.0
# source: ADR-1112 three queued readers make the queue visible
READERS = 3
# source: ADR-1112 the child client
_PROBE = Path(__file__).resolve().with_name("lock_chain_probe.py")
# source: PostgreSQL pg_stat_activity and pg_blocking_pids
_ACTIVITY = (
    "SELECT pid, application_name AS app, state, wait_event_type, wait_event,"
    " pg_blocking_pids(pid) AS blocked_by, left(query, 90) AS query"
    " FROM pg_stat_activity WHERE datname = current_database()"
    " AND pid <> pg_backend_pid() ORDER BY pid"
)
# source: PostgreSQL pg_locks
_LOCKS = (
    "SELECT a.application_name AS app, l.pid, l.mode, l.granted"
    " FROM pg_locks l JOIN pg_stat_activity a USING (pid)"
    " WHERE l.relation = 'memories'::regclass ORDER BY l.granted DESC, l.pid"
)


class Probe:
    """One client process running a given tree (scripts/lock_chain_probe.py)."""

    def __init__(self, tree: Path, mode: str, url: str, app: str) -> None:
        import os  # noqa: PLC0415 -- environment for the child only

        env = dict(os.environ, PGAPPNAME=app)
        self.proc = subprocess.Popen(
            [sys.executable, str(_PROBE), str(tree), mode, url],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.proc.stdout or []:
            self.lines.put(line.strip())

    def wait(self, token: str, seconds: float = WAIT_S) -> str | None:
        """First line starting with ``token`` (or ``REFUSED``), else None."""
        end = time.monotonic() + seconds
        while (left := end - time.monotonic()) > 0:
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                return None
            if line.startswith((token, "REFUSED")):
                return line
        return None

    def send(self, word: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(word + "\n")
        self.proc.stdin.flush()

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()


def connect(url: str, app: str, autocommit: bool = True):
    return psycopg.connect(url, autocommit=autocommit, application_name=app)


def capture(monitor) -> dict:
    activity = [
        dict(zip(_cols(monitor, _ACTIVITY), r, strict=True))
        for r in _rows(monitor, _ACTIVITY)
    ]
    apps = {row["pid"]: row["app"] for row in activity}
    for row in activity:
        row["blocked_by_apps"] = [apps.get(p, str(p)) for p in row["blocked_by"]]
    locks = [
        dict(zip(_cols(monitor, _LOCKS), r, strict=True))
        for r in _rows(monitor, _LOCKS)
    ]
    return {"activity": activity, "locks_on_memories": locks}


def _rows(monitor, sql: str) -> list[tuple]:
    return monitor.execute(sql).fetchall()


def _cols(monitor, sql: str) -> list[str]:
    cur = monitor.execute(sql + " LIMIT 0")
    return [c.name for c in cur.description or []]


def wait_until(monitor, predicate, seconds: float = WAIT_S) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate(capture(monitor)["activity"]):
            return True
        time.sleep(0.1)
    return False


def lock_waiters(activity: list[dict], prefix: str) -> int:
    return sum(
        1
        for row in activity
        if row["app"].startswith(prefix) and row["wait_event_type"] == "Lock"
    )


def start_readers(url: str, done: dict[str, float]) -> list[threading.Thread]:
    def read(app: str) -> None:
        with connect(url, app) as conn:
            conn.execute("SELECT count(*) FROM memories").fetchone()
        done[app] = time.monotonic()

    threads = [
        threading.Thread(target=read, args=(f"reader-{i}",), daemon=True)
        for i in range(READERS)
    ]
    for thread in threads:
        thread.start()
    return threads


def ddl_lines(log: Path, offset: int, app_prefix: str) -> tuple[int, list[str]]:
    text = log.read_text(encoding="utf-8", errors="replace")
    lines = [
        ln.strip()[:160]
        for ln in text[offset:].splitlines()
        if "statement:" in ln and f" {app_prefix}" in ln
    ]
    return len(text), lines
