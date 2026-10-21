"""Acceptance A5 (ADR-1112): an interactive request is served within its
deadline while the background queue is full.

A real broker process on a private cluster, 20000 memories, 32 clients
looping on heavy reads (5000-row keyset pages) against a queue of 8, and one
client timing a point read. One variable: the class the heavy load is sent
in. As background work it may hold at most POOL_BATCH_MAX workers and waits
in its own queue; sent as interactive (what a broker without classes would
do) it competes with the point reads in one FIFO.

Records its numbers through ``CORTEX_REPRO_JSON``
(``python scripts/repro_connection_broker.py priority``).

source: ADR-1112 decision 4, acceptance A5
"""

from __future__ import annotations

import json
import math
import os
import statistics
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
    # about 70 s: run by the broker-measurements CI job and by
    # `python scripts/repro_connection_broker.py priority`, not by every suite run
    pytest.mark.skipif(
        not (
            os.environ.get("CORTEX_BROKER_MEASUREMENTS")
            or os.environ.get("CORTEX_REPRO_JSON")
        ),
        reason="set CORTEX_BROKER_MEASUREMENTS=1 (measurement, about 70 s)",
    ),
]

_REPO = Path(__file__).resolve().parents[2]
# source: ADR-1112 A5 protocol (load shape; see the module docstring)
_ROWS, _HEAVY_CLIENTS, _PAGE, _QUEUE, _SECONDS = 20_000, 32, 5_000, 8, 8.0


def _seed(url: str) -> None:
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415 — PG-only import

    apply_schema(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO memories (content, embedding) SELECT 'memory ' || g,"
            " array_fill(0.1::real, ARRAY[384])::vector"
            " FROM generate_series(1, %s) g",
            (_ROWS,),
        )


def _launcher(root: Path, children: list):
    def launch(module, arguments, environment, fds, output):
        env = {**os.environ, **environment, "CORTEX_CLAUDE_DIR": str(root)}
        env.update(
            CORTEX_BROKER_QUEUE_LIMIT=str(_QUEUE), CORTEX_BROKER_IDLE_SECONDS="5"
        )
        children.append(
            subprocess.Popen(
                [sys.executable, "-m", module, *arguments],
                pass_fds=fds,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                cwd=_REPO,
                env=env,
            )
        )

    return launch


def _measure(url: str, root: Path, heavy_class: str) -> dict:
    from mcp_server.infrastructure import broker_endpoint  # noqa: PLC0415
    from mcp_server.infrastructure.store_operations import request_class  # noqa: PLC0415

    stop = threading.Event()
    heavy_done = [0]

    def heavy():
        store = broker_endpoint.broker_store(url, root, "repro")
        with request_class(heavy_class):
            while not stop.is_set():
                store._fetch_decay_page(_PAGE, None)  # noqa: SLF001 — the stream's page
                heavy_done[0] += 1

    threads = [
        threading.Thread(target=heavy, daemon=True) for _ in range(_HEAVY_CLIENTS)
    ]
    for thread in threads:
        thread.start()
    time.sleep(1.0)  # source: A5 protocol, let the queue fill before timing
    probe = broker_endpoint.broker_store(url, root, "repro")
    latencies: list[float] = []
    started = time.monotonic()
    while time.monotonic() - started < _SECONDS:
        t0 = time.monotonic()
        probe.get_memory(1)
        latencies.append((time.monotonic() - t0) * 1000.0)
    stop.set()
    for thread in threads:
        thread.join(timeout=120)
    latencies.sort()
    return {
        "heavy_class": heavy_class,
        "point_reads": len(latencies),
        "p50_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(
            latencies[math.ceil(0.95 * len(latencies)) - 1], 1
        ),  # nearest rank
        "max_ms": round(latencies[-1], 1),
        "heavy_pages_served": heavy_done[0],
    }


def _record(result: dict) -> None:
    target = os.environ.get("CORTEX_REPRO_JSON")
    if target:
        Path(target).write_text(json.dumps(result))


def test_interactive_requests_keep_their_capacity_under_a_full_background_queue():
    from mcp_server.infrastructure import broker_endpoint  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="a5-", dir=Path("/tmp").resolve()) as raw:
        root = Path(raw)
        children: list[subprocess.Popen] = []
        launch = _launcher(root, children)
        previous = broker_endpoint._launcher  # noqa: SLF001 — test launcher
        broker_endpoint.configure_broker_launcher(launch)
        try:
            with cluster.private_cluster(root / "pg", max_connections=40) as maint:
                with psycopg.connect(maint, autocommit=True) as conn:
                    conn.execute("CREATE DATABASE a5")
                url = maint.rpartition("/")[0] + "/a5"
                _seed(url)
                background = _measure(url, root, "background")
                fifo = _measure(url, root, "interactive")
        finally:
            broker_endpoint._launcher = previous  # noqa: SLF001
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
    result = {"background": background, "single_class": fifo, "brokers": len(children)}
    _record(result)
    assert len(children) == 1  # one broker served both runs
    assert background["p95_ms"] < 30_000.0  # A5: within the interactive deadline
    assert background["p95_ms"] < fifo["p95_ms"]  # the classes are what protect it
    assert background["heavy_pages_served"] > 0  # background still progresses
