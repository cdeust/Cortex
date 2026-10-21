"""Reproduce the 2026-10-20 saturation: per-process pools + one idle
transaction + one DDL exhaust ``max_connections``.

Characterisation test of the CURRENT design (ADR-1112 measurement step):
every Cortex process (MCP server, each hook, ``consolidate_background``)
opens its own ``PgMemoryStore``, i.e. one persistent connection plus an
interactive pool of ``POOL_INTERACTIVE_MIN`` (memory_config.py:152). Here,
on a private cluster with ``max_connections = 20``:

1. a reader leaves a transaction open on ``memories`` (the role the
   consolidation stream played, pg_store_query_stream.py before ADR-1112);
2. a no-op ``ALTER TABLE memories ADD COLUMN IF NOT EXISTS`` queues for
   AccessExclusive behind it (the role a runtime migration played);
3. ``_CHILDREN`` hook-like processes each open a store and run one pooled
   read, which queues behind the ALTER.

The assertions pin what the incident showed: the blocked processes keep
their connections for as long as the reader lives, and the processes that
come after them are refused (``too many clients``) or time out on their
pool. When the broker of ADR-1112 lands, this test is inverted into its
acceptance criterion: the same scenario must leave backends bounded by the
broker's pool, whatever ``_CHILDREN`` is.

Run with ``-s`` to print the measured numbers.

source: ADR-1112
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests_py import _pg_private_cluster as cluster

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(
    not cluster.available(), reason="initdb/pg_ctl not on PATH"
)

# source: ADR-1112 measurement; small enough that 8 hook-like processes at
# 1 persistent + POOL_INTERACTIVE_MIN..MAX pooled connections each overflow it.
_MAX_CONNECTIONS = 20
# source: ADR-1112 measurement; more processes than the cluster can seat.
_CHILDREN = 8
# source: harness bound only (12x the 5 s POOL_INTERACTIVE_TIMEOUT_S), never a fix.
_SETTLE_DEADLINE_S = 60.0
_REPO = Path(__file__).resolve().parents[2]
_NOOP_ALTER = (
    "ALTER TABLE memories ADD COLUMN IF NOT EXISTS "
    "is_team_decision BOOLEAN NOT NULL DEFAULT FALSE"
)
_CHILD = """
import os, sys
try:
    from mcp_server.infrastructure.pg_store import PgMemoryStore
    store = PgMemoryStore(database_url=os.environ["DATABASE_URL"])
    store._execute("SELECT count(*) FROM memories").fetchone()
    store.close()
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}".splitlines()[0])
    sys.exit(3)
"""


def _spawn(url: str, index: int) -> subprocess.Popen[str]:
    env = dict(os.environ, DATABASE_URL=url)
    return subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        cwd=_REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _backends(monitor) -> dict[str, tuple[int, int]]:
    """Owner -> (backends, backends waiting on a lock). A store connection is
    named ``cortex-store-<pool>-<pid>`` (pg_session_bounds); its owner is the
    PID. Other backends keep their application_name."""
    rows = monitor.execute(
        "SELECT CASE WHEN application_name LIKE 'cortex-store-%%'"
        " THEN 'pid-' || split_part(application_name, '-', 4)"
        " ELSE application_name END AS owner, count(*),"
        " count(*) FILTER (WHERE wait_event_type = 'Lock')"
        " FROM pg_stat_activity WHERE backend_type = 'client backend'"
        " GROUP BY owner"
    ).fetchall()
    return {name: (total, waiting) for name, total, waiting in rows}


def _settle(children, monitor) -> dict[str, tuple[int, int]]:
    """Poll until every child has exited or waits on a lock (bounded)."""
    deadline = time.monotonic() + _SETTLE_DEADLINE_S
    while True:
        seen = _backends(monitor)
        pending = [
            i
            for i, child in enumerate(children)
            if child.poll() is None and seen.get(f"pid-{child.pid}", (0, 0))[1] == 0
        ]
        if not pending or time.monotonic() > deadline:
            return seen
        time.sleep(0.2)


def _schema(url: str) -> str:
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415 — PG-only import

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE DATABASE cortex_saturation")
    target = url.rsplit("/", 1)[0] + "/cortex_saturation"
    apply_schema(target)
    return target


def _record(measured: dict) -> None:
    """Hand the numbers to scripts/repro_connection_broker.py when it asks."""
    target = os.environ.get("CORTEX_REPRO_JSON")
    if target:
        Path(target).write_text(json.dumps(measured), encoding="utf-8")


def _run_scenario(tmp_path: Path, children: int) -> dict:
    """Idle reader + queued no-op ALTER + ``children`` hook-like processes."""
    with cluster.private_cluster(tmp_path, _MAX_CONNECTIONS) as maint:
        url = _schema(maint)
        monitor = psycopg.connect(url, autocommit=True)
        reader = psycopg.connect(url)
        reader.execute("SELECT 1 FROM memories LIMIT 1")  # idle in transaction
        ddl = psycopg.connect(url, autocommit=True)
        alter = threading.Thread(target=ddl.execute, args=(_NOOP_ALTER,), daemon=True)
        alter.start()
        procs = [_spawn(url, i) for i in range(children)]
        try:
            seen = _settle(procs, monitor)
            refused = [c for c in procs if c.poll() is not None]
        finally:
            reader.rollback()
            alter.join(timeout=30)
            outcomes = [c.communicate(timeout=60)[0].strip() for c in procs]
            for conn in (reader, ddl, monitor):
                conn.close()
    pids = {f"pid-{c.pid}" for c in procs}
    held = {k: v for k, v in seen.items() if k in pids}
    return {
        "max_connections": _MAX_CONNECTIONS,
        "children": children,
        "backends_at_peak": sum(v[0] for v in seen.values()),
        "per_blocked_child": sorted(v[0] for v in held.values()),
        "blocked_children": sum(1 for v in held.values() if v[1] > 0),
        "refused_or_timed_out": len(refused),
        "outcomes": [o for o in outcomes if o],
    }


def test_per_process_pools_exhaust_max_connections(tmp_path):
    measured = _run_scenario(tmp_path, _CHILDREN)
    print(f"\n[saturation] {measured}")
    _record(measured)
    assert measured["refused_or_timed_out"], "saturation not reproduced"
    assert any(
        "too many clients" in o
        or "PoolTimeout" in o
        or "couldn't get a connection" in o
        for o in measured["outcomes"]
    ), measured
    assert measured["blocked_children"], "no child queued behind the ALTER"
    assert min(measured["per_blocked_child"]) >= 2, measured
