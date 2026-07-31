"""Tests for the session-counted shared groomer coordinator (issue #171).

Done criteria proven here:
  * two concurrent sessions produce EXACTLY ONE grooming cycle per period
    (``test_two_sessions_one_cycle_per_period`` + the real two-process
    ``test_two_processes_one_cycle`` for genuine lock contention);
  * a killed (dead-pid) session's registration is reclaimed by the next
    session's liveness sweep and grooming continues
    (``test_crash_dead_pid_reclaimed`` / ``test_crash_does_not_block_cycle``);
  * deregistering all sessions stops the groomer
    (``test_last_exit_stops_groomer``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.infrastructure.groomer_coordinator import (
    SKIPPED_FRESH,
    SKIPPED_RUNNING,
    STARTED,
    GroomerCoordinator,
    resolve_store_key,
)
import pathlib


def test_resolve_store_key_resolves_real_identity_not_default():
    """The SQLite store key must be a real 16-hex hash of the store path, NOT
    the ``"default"`` degrade sentinel. Guards the regression where an
    invented import symbol made ``resolve_store_key`` raise ImportError and
    silently collapse every store onto one shared ``"default"`` key."""
    key = resolve_store_key({"CORTEX_MEMORY_STORE_BACKEND": "sqlite"})
    assert key != "default"
    assert len(key) == 16
    assert all(c in "0123456789abcdef" for c in key)


def test_resolve_store_key_distinct_pg_urls_distinct_keys():
    """Two different PostgreSQL DATABASE_URLs resolve to different keys — the
    per-store isolation the coordinator depends on."""
    a = resolve_store_key({"DATABASE_URL": "postgresql://h/db_a"})
    b = resolve_store_key({"DATABASE_URL": "postgresql://h/db_b"})
    assert a != b and a != "default" and b != "default"


_PERIOD_H = 6.0


def _coord(tmp_path, store_key="store-a"):
    return GroomerCoordinator(store_key, root=tmp_path)


class _SpawnCounter:
    """A fake ``spawn_fn``: counts calls, returns a live pid (this process's
    own, so ``is_groomer_running`` reads it as alive) unless ``dead`` is set."""

    def __init__(self, *, dead: bool = False):
        self.calls = 0
        self.dead = dead

    def __call__(self):
        self.calls += 1
        # A dead pid lets us exercise the single-instance guard NOT latching
        # on a crashed cycle; a live pid (os.getpid) latches it.
        return -1 if self.dead else os.getpid()


# ── done criterion 1: exactly one cycle per period across N sessions ─────


def test_two_sessions_one_cycle_per_period(tmp_path):
    """Two sessions against the same store: the first ensures the cycle, the
    second sees a fresh period stamp and skips — spawn runs exactly once."""
    store = resolve_store_key({"CORTEX_MEMORY_STORE_BACKEND": "sqlite"})
    a = _coord(tmp_path, store)
    b = _coord(tmp_path, store)
    spawn = _SpawnCounter()

    a.register(1111)
    b.register(2222)

    now = datetime.now(timezone.utc)
    r1 = a.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=now)
    r2 = b.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=now)

    assert r1 == STARTED
    assert r2 in (SKIPPED_FRESH, SKIPPED_RUNNING)
    assert spawn.calls == 1  # EXACTLY ONE grooming cycle this period


def test_new_cycle_after_period_elapses(tmp_path):
    """Once the period elapses, the next ensure spawns again — the gate is a
    period, not a permanent latch."""
    c = _coord(tmp_path)
    spawn = _SpawnCounter(dead=True)  # dead pid → no single-instance latch
    now = datetime.now(timezone.utc)

    assert c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=now) == STARTED
    # Still within the period → skipped.
    assert (
        c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=now) == SKIPPED_FRESH
    )
    later = now + timedelta(hours=_PERIOD_H + 0.1)
    assert c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=later) == STARTED
    assert spawn.calls == 2


def test_single_instance_guard_blocks_second_spawn_same_period(tmp_path):
    """A still-running cycle (live pid) blocks a second spawn even at the
    period edge — single-instance enforcement via pid liveness."""
    c = _coord(tmp_path)
    spawn = _SpawnCounter()  # live pid → latches groomer.pid
    now = datetime.now(timezone.utc)
    assert c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=now) == STARTED
    assert c.is_groomer_running() is True
    later = now + timedelta(hours=_PERIOD_H + 1)  # period elapsed...
    # ...but the previous cycle is still alive → single-instance skip.
    assert (
        c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=later)
        == SKIPPED_RUNNING
    )
    assert spawn.calls == 1


# ── done criterion 2: crash-safe registration reclaim ────────────────────


def test_crash_dead_pid_reclaimed(tmp_path):
    """A registration for a dead pid is swept and does not count as live."""
    c = _coord(tmp_path)
    c.register(999999999)  # a pid that is not alive
    c.register(os.getpid())  # a live one
    assert c.live_session_count() == 1  # dead one reclaimed
    # The dead registration file is gone after the sweep.
    assert not (c.sessions_dir / "999999999.json").exists()


def test_crash_does_not_leave_groomer_latched(tmp_path):
    """A crashed cycle (dead groomer.pid) must not latch the single-instance
    guard forever — the next period's ensure spawns again."""
    c = _coord(tmp_path)
    dead = _SpawnCounter(dead=True)
    now = datetime.now(timezone.utc)
    assert c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=dead, now=now) == STARTED
    # groomer.pid names a dead pid → not running.
    assert c.is_groomer_running() is False
    later = now + timedelta(hours=_PERIOD_H + 0.1)
    assert c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=dead, now=later) == STARTED
    assert dead.calls == 2  # grooming continued after the crash


def test_crash_next_session_still_grooms(tmp_path):
    """Simulated kill -9: session A registers then dies; session B's sweep
    reclaims A and B can still ensure a cycle."""
    store = "crash-store"
    a = _coord(tmp_path, store)
    a.register(888888888)  # A (will be treated as dead)
    b = _coord(tmp_path, store)
    b.register(os.getpid())
    assert b.live_session_count() == 1  # A reclaimed
    spawn = _SpawnCounter(dead=True)
    assert b.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn) == STARTED


# ── done criterion 3: last exit stops the groomer ────────────────────────


def test_last_exit_stops_groomer(tmp_path):
    """Deregister all sessions → the last one triggers stop; earlier ones
    do not."""
    c = _coord(tmp_path)
    c.register(1)
    c.register(2)
    # Simulate both pids being alive by using real live pids is overkill;
    # instead assert the stop fires only when no live registration remains.
    # Use dead pids so live_session_count reflects only what we deregister.
    stopped = {"n": 0}

    def stop_fn():
        stopped["n"] += 1

    # pids 1 and 2 are (almost certainly) not this test's live children;
    # live_session_count sweeps them, so the FIRST stop_if_last already
    # finds zero live and fires. Model the count explicitly with live pids:
    c2 = _coord(tmp_path, "last-exit-store")
    p_live = os.getpid()
    c2.register(p_live)
    # Register a second *live* pid: spawn a short-lived sleeper.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        c2.register(sleeper.pid)
        # First exit (this process pid): sleeper still alive → NOT last.
        assert c2.stop_if_last(p_live, stop_fn=stop_fn) is False
        assert stopped["n"] == 0
        # Second exit (sleeper): now zero live → last exit stops.
        assert c2.stop_if_last(sleeper.pid, stop_fn=stop_fn) is True
        assert stopped["n"] == 1
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)


def test_stop_clears_single_instance_marker(tmp_path):
    """Last-exit stop clears groomer.pid so a stale marker cannot survive
    the last session."""
    c = _coord(tmp_path)
    spawn = _SpawnCounter()  # latches groomer.pid with a live pid
    c.register(os.getpid())
    c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn)
    assert c.pid_path.exists()
    c.stop_if_last(os.getpid())
    assert not c.pid_path.exists()


# ── observability: duplicate-run counter over a window ───────────────────


def test_cycle_count_over_window_is_one_per_period(tmp_path):
    """The runs.log-backed counter reports exactly one STARTED per period —
    the mechanism for the issue's 24h zero-duplication operational evidence."""
    c = _coord(tmp_path)
    spawn = _SpawnCounter(dead=True)
    base = datetime.now(timezone.utc) - timedelta(hours=24)
    # 24h / 6h period = at most 4 cycles; drive 24 hourly session opens.
    for h in range(24):
        now = base + timedelta(hours=h)
        for _sess in range(3):  # three concurrent-ish sessions per hour
            c.ensure_cycle(period_hours=_PERIOD_H, spawn_fn=spawn, now=now)
    started = c.count_cycles_since(base - timedelta(minutes=1))
    # 24h split into 6h windows → exactly 4 cycles, never 72 (3*24).
    assert started == 4


# ── real two-process contention (genuine concurrency) ────────────────────

_CHILD = """
import sys
from datetime import datetime, timezone
from mcp_server.infrastructure.groomer_coordinator import GroomerCoordinator, STARTED
root = sys.argv[1]
from pathlib import Path
c = GroomerCoordinator("proc-store", root=Path(root))
now = datetime.now(timezone.utc)
# A spawn_fn that appends a marker file so the parent can count real spawns.
def spawn():
    p = Path(root) / "spawns"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write("x")
    return -1  # dead pid: no single-instance latch, so ONLY the period
               # stamp+lock decide — the strict test of the barrier.
out = c.ensure_cycle(period_hours=6.0, spawn_fn=spawn, now=now)
print(out)
"""


@pytest.mark.skipif(os.name == "nt", reason="flock semantics differ on Windows")
def test_two_processes_one_cycle(tmp_path):
    """Two real OS processes race ``ensure_cycle`` against one store. The
    per-store lock + stamp barrier admit exactly one spawn."""
    root = tmp_path / "coord"
    env = {**os.environ, "PYTHONPATH": str(pathlib.Path.cwd())}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(root)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=60) for p in procs]
    for p in procs:
        assert p.returncode == 0, outs

    spawns_file = root / "spawns"
    spawn_count = len(spawns_file.read_text()) if spawns_file.exists() else 0
    assert spawn_count == 1, f"expected exactly one spawn, got {spawn_count}: {outs}"
    started = sum(1 for out, _err in outs if out.strip() == STARTED)
    assert started == 1
