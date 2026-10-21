"""Acceptance A6 (ADR-1112): recall through the broker against in-process.

The release benchmark's own retrieval path (``BenchmarkDB.recall`` is
``mcp_server.core.pg_recall.recall`` on a store), one variable: the store
it runs on, the in-process ``PgMemoryStore`` or the broker's client, on the
same private-cluster database. A deterministic corpus of 3000 memories is
ingested through ``ingest_memories_batch`` (the benchmark's loader); 150
queries run on each store, alternating, after a warm-up. Recorded: p50 and
p95 latency of each. Parity is checked first, before any recall writes
(access heat), on the read-only store call the broker carries
(``recall_memories``, a STABLE SQL function): see ``_parity``. Reranking is off
on both sides: it runs in the client process either way.

``benchmarks/reproduce.sh`` itself needs Docker (its PostgreSQL is a
container) and the LongMemEval files; this measurement is the transport
variable alone.

Records its numbers through ``CORTEX_REPRO_JSON``
(``python scripts/repro_connection_broker.py latency``).

source: ADR-1112 acceptance A6
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
import tempfile
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
        reason="set CORTEX_BROKER_MEASUREMENTS=1 (measurement, about 5 min)",
    ),
    # source: experiment log, 288 s (04:40Z latency entry) against the suite's
    # 300 s default (pyproject.toml); a timeout at load average 19 on 2026-10-21
    pytest.mark.timeout(1200),
]

# source: ADR-1112 A6 protocol (corpus size, query count, warm-up)
_MEMORIES, _QUERIES, _WARMUP = 3000, 150, 10
_WORDS = (
    "broker pool lease socket schema migration recall memory heat decay "
    "consolidation wiki claim entity relationship vector trigram index "
    "session hook capture transcript agent decision lesson pattern error "
    "postgres connection transaction deadline queue backpressure priority"
).split()


def _corpus(rng: random.Random) -> list[dict]:
    return [
        {"content": " ".join(rng.choices(_WORDS, k=24)) + f" fact {i}"}
        for i in range(_MEMORIES)
    ]


def _percentile(sorted_ms: list[float], q: float) -> float:
    return round(sorted_ms[math.ceil(q * len(sorted_ms)) - 1], 2)  # nearest rank


def _ids(rows: list[dict]) -> list[int]:
    return [row.get("memory_id", row.get("id")) for row in rows]


def _parity(local, other, embeddings, queries: list[str]) -> dict[str, int]:
    """Same ranked ids on ``other`` as on ``local``, before any write. Each
    ``other`` call is bracketed by two ``local`` calls: ``recall_memories``
    scores heat at ``NOW()``, so two calls at different instants can rank
    close scores differently; a query counts as a mismatch only when the two
    ``local`` rankings agree and ``other``'s differs from them."""
    unstable = mismatched = 0
    for query in queries:
        vector = embeddings.encode(query)
        before = _ids(local.recall_memories(query, vector, include_globals=False))
        through = _ids(other.recall_memories(query, vector, include_globals=False))
        after = _ids(local.recall_memories(query, vector, include_globals=False))
        if before != after:
            unstable += 1
        elif through != before:
            mismatched += 1
    return {"time_unstable": unstable, "mismatched": mismatched}


def _recall(store, embeddings, query: str) -> tuple[float, list[int]]:
    from mcp_server.core.pg_recall import recall  # noqa: PLC0415

    started = time.perf_counter()
    results = recall(
        query=query,
        store=store,
        embeddings=embeddings,
        top_k=10,
        rerank=False,
        include_globals=False,
        momentum_state={"momentum": 0.5},
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    return elapsed, [r.get("memory_id", r.get("id")) for r in results]


def _parity_arms(url: str, stores: tuple, embeddings, queries: list[str]) -> dict:
    """Before any write: the broker, and a second in-process store as the
    control arm (same code, another set of connections)."""
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415

    local, remote = stores
    control = PgMemoryStore(database_url=url)
    try:
        return {
            "broker": _parity(local, remote, embeddings, queries),
            "control_second_in_process_store": _parity(
                local, control, embeddings, queries
            ),
        }
    finally:
        control.close()


def _timed(local, remote, embeddings, queries: list[str]) -> dict[str, list[float]]:
    """Warm both sides, then alternate them query by query."""
    for query in queries[:_WARMUP]:
        _recall(local, embeddings, query)
        _recall(remote, embeddings, query)
    times: dict[str, list[float]] = {"in_process": [], "broker": []}
    for query in queries:
        times["in_process"].append(_recall(local, embeddings, query)[0])
        times["broker"].append(_recall(remote, embeddings, query)[0])
    return times


def _summary(times: dict, parity: dict, embeddings) -> dict:
    summary: dict = {
        name: {
            "p50_ms": round(statistics.median(values), 2),
            "p95_ms": _percentile(sorted(values), 0.95),
        }
        for name, values in times.items()
    }
    summary["queries"] = _QUERIES
    summary["memories"] = _MEMORIES
    summary["parity"] = parity
    summary["embedding_mode"] = getattr(embeddings, "mode", "unknown")
    return summary


def test_recall_through_the_broker_matches_in_process_and_its_overhead_is_measured(
    broker_env,
):
    from mcp_server.core.memory_ingest import ingest_memories_batch  # noqa: PLC0415
    from mcp_server.infrastructure import broker_endpoint  # noqa: PLC0415
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: PLC0415
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415

    root, _children = broker_env
    rng = random.Random(1112)
    with tempfile.TemporaryDirectory(prefix="a6-") as raw:
        with cluster.private_cluster(Path(raw), max_connections=40) as maint:
            with psycopg.connect(maint, autocommit=True) as conn:
                conn.execute("CREATE DATABASE a6")
            url = maint.rpartition("/")[0] + "/a6"
            apply_schema(url)
            embeddings = EmbeddingEngine()
            local = PgMemoryStore(database_url=url)
            ingest_memories_batch(
                _corpus(rng), local, embeddings, domain="a6", decompose=False
            )
            remote = broker_endpoint.broker_store(url, root, "a6")
            queries = [" ".join(rng.choices(_WORDS, k=5)) for _ in range(_QUERIES)]
            parity = _parity_arms(url, (local, remote), embeddings, queries)
            times = _timed(local, remote, embeddings, queries)
            remote.close()
            local.close()
    summary = _summary(times, parity, embeddings)
    target = os.environ.get("CORTEX_REPRO_JSON")
    if target:
        Path(target).write_text(json.dumps(summary))
    # the broker changes no more rankings than a second in-process store does;
    # source: experiment log entry 19, the control arm alone mismatched 3 of 150
    # (connection-dependent order of close scores), hence the slack of 2
    broker, control = parity["broker"], parity["control_second_in_process_store"]
    assert broker["mismatched"] <= control["mismatched"] + 2, summary
