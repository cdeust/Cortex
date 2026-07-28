"""Subprocess drivers for cross_benchmark_runner.

Each driver is invoked as
`python -m benchmarks.lib._xb_drivers <bench> <data_path> <limit>`
in a fresh subprocess. Env vars (CORTEX_DECAY_LAMBDA, CORTEX_MEMORY_*) are set
by the parent before exec — the driver does not parse them. The driver runs
the inner benchmark loop and emits a single line `__JSON__{...}` to stdout.

Subprocess isolation is required because mcp_server.core.thermodynamics
reads CORTEX_DECAY_LAMBDA at module import time and the lru_cache(maxsize=1)
on get_memory_settings pins the first observed value.
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.locomo.data import extract_sessions, load_locomo

# source: structural — the K in the reported recall_at_10 metric
_RECALL_AT_10_K = 10

# source: structural — argv is [script, bench, data_path, limit]
_EXPECTED_ARGC = 4


def _drive_longmemeval(data_path: str, limit: int) -> dict:
    from benchmarks.longmemeval.run_benchmark import run_benchmark  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

    r = run_benchmark(data_path, limit=limit)
    return {
        "mrr": r["overall_mrr"],
        "recall_at_10": r["overall_recall10"],
        "category_mrr": r.get("category_mrr", {}),
        "category_recall10": r.get("category_recall10", {}),
        "elapsed_s": r.get("elapsed_s", 0.0),
    }


def _drive_locomo(data_path: str, limit: int) -> dict:
    from benchmarks.lib.bench_db import BenchmarkDB  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it
    from benchmarks.locomo.run_benchmark import evaluate_conversation  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

    data = load_locomo(data_path)
    if limit:
        data = data[:limit]

    agg: dict[str, list[dict]] = defaultdict(list)
    t0 = time.time()
    # require_reranker=True: this driver backs cross_benchmark_runner's
    # Popper C5 generalization claim, which explicitly sweeps FlashRank
    # top-K as one of its load-bearing knobs (cross_benchmark_runner.py
    # docstring) -- the claim is meaningless without a genuinely loaded
    # cross-encoder (INC7.2 audit).
    with BenchmarkDB(require_reranker=True) as db:
        for conv in data:
            sessions = extract_sessions(conv["conversation"])
            db.clear()
            memories = [
                {
                    "content": s["content"],
                    "user_content": s.get("user_content", ""),
                    "created_at": s.get("date", ""),
                    "source": f"session_{s['session_idx']}",
                    "tags": ["locomo"],
                }
                for s in sessions
            ]
            mids, smap = db.load_memories(memories, domain="locomo")
            cr = evaluate_conversation(db, sessions, mids, smap, conv["qa"])
            for c, rs in cr.items():
                agg[c].extend(rs)
    elapsed = time.time() - t0
    all_rs = [r for rs in agg.values() for r in rs]
    n = len(all_rs)
    mrr = sum(1.0 / r["hit_rank"] for r in all_rs if r["hit_rank"]) / n if n else 0.0
    r10 = (
        sum(1 for r in all_rs if r["hit_rank"] and r["hit_rank"] <= _RECALL_AT_10_K) / n
        if n
        else 0.0
    )
    cat_mrr: dict[str, float] = {}
    cat_r10: dict[str, float] = {}
    for cat, rs in agg.items():
        if not rs:
            continue
        m = len(rs)
        cat_mrr[cat] = sum(1.0 / r["hit_rank"] for r in rs if r["hit_rank"]) / m
        cat_r10[cat] = (
            sum(1 for r in rs if r["hit_rank"] and r["hit_rank"] <= _RECALL_AT_10_K) / m
        )
    return {
        "mrr": mrr,
        "recall_at_10": r10,
        "n_questions": n,
        "category_mrr": cat_mrr,
        "category_recall10": cat_r10,
        "elapsed_s": elapsed,
    }


def main() -> int:
    if len(sys.argv) != _EXPECTED_ARGC:
        print(
            "usage: _xb_drivers.py <longmemeval|locomo> <data_path> <limit>",
            file=sys.stderr,
        )
        return 2
    bench, data_path, limit_s = sys.argv[1], sys.argv[2], sys.argv[3]
    limit = int(limit_s)
    if bench == "longmemeval":
        out = _drive_longmemeval(data_path, limit)
    elif bench == "locomo":
        out = _drive_locomo(data_path, limit)
    else:
        print(f"unknown benchmark: {bench}", file=sys.stderr)
        return 2
    print("__JSON__" + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
