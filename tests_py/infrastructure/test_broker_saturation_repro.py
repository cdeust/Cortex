"""Acceptance A1 (ADR-1112): the baseline saturation scenario, inverted.

Same control environment as ``test_pg_connection_saturation_repro.py`` (a
private cluster with ``max_connections = 20``, one idle reader, one queued
no-op ``ALTER TABLE``) and the same hook-like children, except that each
child gets its store from the factory, as every Cortex process now does, so
it talks to the store broker. Measured with 8 and with 64 children: Cortex
backends at peak, the PIDs they belong to, children refused or failed. On
main the 8-child run refused 4 or 5 of 8 children and each blocked child
held 2 to 4 connections (experiment log entry 5 and the ``baseline``
entries). Then the reader ends its transaction and every child must finish.

Records its numbers through ``CORTEX_REPRO_JSON``
(``python scripts/repro_connection_broker.py saturation``).

source: ADR-1112 acceptance A1
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from tests_py import _pg_private_cluster as cluster

psycopg = pytest.importorskip("psycopg")

pytestmark = [
    pytest.mark.skipif(not cluster.available(), reason="initdb/pg_ctl not on PATH"),
    pytest.mark.skipif(sys.platform == "win32", reason="Unix transport"),
    pytest.mark.skipif(
        not (
            os.environ.get("CORTEX_BROKER_MEASUREMENTS")
            or os.environ.get("CORTEX_REPRO_JSON")
        ),
        reason="set CORTEX_BROKER_MEASUREMENTS=1 (measurement, about 2 min)",
    ),
]

_REPO = Path(__file__).resolve().parents[2]
# source: test_pg_connection_saturation_repro (the control environment)
_MAX_CONNECTIONS = 20
# source: ADR-1112 A1 (one broker: P = 11 connections, plus the migration one)
_P_PLUS_ONE = 12
# source: ADR-1112 A1 protocol: long enough for 64 interpreters to start,
# below the broker's 30 s lock_timeout on the blocked reads
_SETTLE_SECONDS = 20.0
_NOOP_ALTER = (
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS "
    "is_team_decision BOOLEAN NOT NULL DEFAULT FALSE"
)
_CHILD = """
import sys
try:
    from mcp_server.hooks.wiring import wire_composition_root
    wire_composition_root()
    from mcp_server.infrastructure.memory_store import get_shared_store
    store = get_shared_store()
    store.count_memories()
    store.close()
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}".splitlines()[0])
    sys.exit(3)
"""


def _cortex_backends(monitor) -> tuple[int, set[str], int, dict[str, int]]:
    rows = monitor.execute(
        "SELECT application_name, wait_event_type FROM pg_stat_activity"
        " WHERE backend_type = 'client backend'"
        " AND application_name LIKE 'cortex-store-%%'"
    ).fetchall()
    owners = {name.rsplit("-", 1)[1] for name, _ in rows}
    waiting = sum(1 for _, wait in rows if wait == "Lock")
    pools: dict[str, int] = {}
    for name, _ in rows:
        pool = name.split("-")[2]
        pools[pool] = pools.get(pool, 0) + 1
    return len(rows), owners, waiting, pools


def _start_children(url: str, root: Path, children: int) -> list:
    env = {**os.environ, "DATABASE_URL": url, "CORTEX_CLAUDE_DIR": str(root)}
    env.pop("CORTEX_STORE_IN_PROCESS", None)
    env["CORTEX_BROKER_IDLE_SECONDS"] = "3"
    return [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD],
            cwd=_REPO,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        for _ in range(children)
    ]


def _watch(monitor) -> tuple[int, set, int, dict]:
    """Peak Cortex backends (and by pool), owner PIDs, peak waiting on the
    ``ALTER``, sampled until the scenario has settled."""
    peak, owners, waiting_peak, peak_pools = 0, set(), 0, {}
    deadline = time.monotonic() + _SETTLE_SECONDS
    while time.monotonic() < deadline:
        total, seen, waiting, pools = _cortex_backends(monitor)
        if total > peak:
            peak, peak_pools = total, pools
        waiting_peak = max(waiting_peak, waiting)
        owners |= seen
        time.sleep(0.2)  # source: A1 protocol sampling period
    return peak, owners, waiting_peak, peak_pools


def _scenario(root: Path, children: int) -> dict:
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415

    with cluster.private_cluster(root / f"pg{children}", _MAX_CONNECTIONS) as maint:
        with psycopg.connect(maint, autocommit=True) as conn:
            conn.execute("CREATE DATABASE a1")
        url = maint.rpartition("/")[0] + "/a1"
        apply_schema(url)
        monitor = psycopg.connect(url, autocommit=True)
        reader = psycopg.connect(url)
        reader.execute("SELECT 1 FROM memories LIMIT 1")  # idle in transaction
        ddl = psycopg.connect(url, autocommit=True)
        alter = threading.Thread(target=ddl.execute, args=(_NOOP_ALTER,), daemon=True)
        alter.start()
        procs = _start_children(url, root, children)
        peak, owners, waiting_peak, peak_pools = _watch(monitor)
        failed_before_release = sum(1 for p in procs if p.poll() not in (None, 0))
        reader.rollback()
        alter.join(timeout=30)
        outcomes = [p.communicate(timeout=120)[0].strip() for p in procs]
        codes = [p.returncode for p in procs]
        for conn in (reader, ddl, monitor):
            conn.close()
        for pid in owners:
            subprocess.run(["kill", pid], check=False)
    return {
        "children": children,
        "max_connections": _MAX_CONNECTIONS,
        "peak_cortex_backends": peak,
        "peak_by_pool": peak_pools,
        "backend_owner_pids": len(owners),
        "peak_waiting_on_the_alter": waiting_peak,
        "failed_before_release": failed_before_release,
        "failed": sum(1 for c in codes if c != 0),
        "outcomes": sorted({o for o in outcomes if o}),
    }


def test_one_broker_keeps_the_saturation_scenario_within_its_pool():
    results = {}
    with tempfile.TemporaryDirectory(prefix="a1-", dir=Path("/tmp").resolve()) as raw:
        for children in (8, 64):
            results[str(children)] = _scenario(Path(raw), children)
    target = os.environ.get("CORTEX_REPRO_JSON")
    if target:
        Path(target).write_text(json.dumps(results))
    for measured in results.values():
        assert measured["peak_cortex_backends"] <= _P_PLUS_ONE, results
        assert measured["backend_owner_pids"] == 1, results
        assert measured["failed"] == 0, results
