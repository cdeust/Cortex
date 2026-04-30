"""E2a — Real-benchmark subsampling for the E2 retrieval claim.

Replays LongMemEval / LoCoMo / BEAM-100K at increasing N by subsampling
their native corpora deterministically. This is the **claim-bearing** E2
retrieval runner; the synthetic-corpus latency runner
(``benchmarks.lib.latency_runner``) is latency-only.

Per N, runs cortex_full + cortex_flat using the shared E2 condition
toggles (``benchmarks.lib._e2_conditions``). Memories are loaded via the
production write path (BenchmarkDB → memory_ingest), and queries go
through the production read path (BenchmarkDB → pg_recall) — same code
as the standalone benchmarks. Outputs JSON per (benchmark, N, cond) and
a summary.csv.

Falsifiability (per tasks/verification-protocol.md §E2): the gap between
cortex_full and cortex_flat MRR on at least one of {LongMemEval-S,
LoCoMo, BEAM-100K} at N=full must be >= 5pp; otherwise the
thermodynamic-structure-matters claim is refuted.

CLI:
    python -m benchmarks.lib.e2_subsample_runner \\
        --benchmark longmemeval-s --n 100 1000 \\
        --queries 50 --seed 42 \\
        --db-url postgresql://localhost:5432/cortex_e2_subsample \\
        [--quick]
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Force CPU embeddings — same convention as longmemeval/run_benchmark.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from benchmarks.lib._e2_conditions import (  # noqa: E402
    CONDITIONS,
    apply_condition,
    heat_for,
    restore_env,
)
from benchmarks.lib._e2_loaders import (  # noqa: E402
    LOADERS,
    QueryProbe,
    SubsampleItem,
)
from benchmarks.lib.bench_db import BenchmarkDB  # noqa: E402

SCHEMA_VERSION = 1
RESULTS_DIR = _ROOT / "benchmarks" / "results" / "e2_subsample"
DEFAULT_DB_URL = "postgresql://localhost:5432/cortex_e2_subsample"
SUPPORTED_BENCHMARKS = tuple(LOADERS.keys())
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


@dataclass
class TrialResult:
    benchmark: str
    n: int
    condition: str
    seed: int
    n_queries: int
    r_at_1: float
    r_at_10: float
    mrr: float
    wall_per_query_ms: float
    rss_peak_mb: float


# ── Subsampling + scoring ────────────────────────────────────────────────


def subsample(
    items: list[SubsampleItem],
    probes: list[QueryProbe],
    n: int,
    n_queries: int,
    seed: int,
) -> tuple[list[SubsampleItem], list[QueryProbe]]:
    """Take prefix of length n; keep probes whose targets remain; sample queries.

    Pre: items already shuffled deterministically by seed (loader does it).
    Post: returned items have len <= n; returned probes have len <= n_queries
    and every probe has at least one target_source_key in the returned items.
    """
    sub_items = items[:n]
    keep_keys = {it.source_key for it in sub_items}
    valid_probes = [
        p for p in probes if any(k in keep_keys for k in p.target_source_keys)
    ]
    rng = random.Random(seed * 31 + 7)
    if len(valid_probes) > n_queries:
        valid_probes = rng.sample(valid_probes, n_queries)
    return sub_items, valid_probes


def evaluate(
    db: BenchmarkDB,
    probes: list[QueryProbe],
    source_map: dict[int, str],
    domain: str,
) -> tuple[float, float, float, float]:
    """Return (r_at_1, r_at_10, mrr, wall_per_query_ms)."""
    hits1 = hits10 = 0
    rr_sum = 0.0
    wall_sum = 0.0
    for probe in probes:
        t0 = time.monotonic()
        results = db.recall(probe.query, top_k=10, domain=domain)
        wall_sum += (time.monotonic() - t0) * 1000.0
        retrieved_keys = [source_map.get(r["memory_id"], "") for r in results]
        target_set = set(probe.target_source_keys)
        rank = next(
            (i + 1 for i, k in enumerate(retrieved_keys) if k in target_set), None
        )
        if rank is not None:
            hits10 += 1
            rr_sum += 1.0 / rank
            if rank == 1:
                hits1 += 1
    n = max(1, len(probes))
    return hits1 / n, hits10 / n, rr_sum / n, wall_sum / n


# ── Trial ────────────────────────────────────────────────────────────────


def _load_subsample_into_db(
    db_url: str,
    benchmark: str,
    sub_items: list[SubsampleItem],
    condition: str,
    sub_probes: list[QueryProbe],
) -> tuple[float, float, float, float, float]:
    """Open BenchmarkDB, load memories, evaluate. Returns (r1, r10, mrr, wall_ms, rss_mb)."""
    saved_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    tracemalloc.start()
    try:
        with BenchmarkDB(database_url=db_url) as db:
            heat = heat_for(condition)
            payload = [{**it.memory, "heat": heat} for it in sub_items]
            _, source_map = db.load_memories(payload, domain=benchmark)
            r1, r10, mrr, wall_per_q = evaluate(db, sub_probes, source_map, benchmark)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if saved_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_db_url
    return r1, r10, mrr, wall_per_q, peak / (1024 * 1024)


def run_trial(
    benchmark: str,
    n: int,
    condition: str,
    seed: int,
    n_queries: int,
    db_url: str,
    items: list[SubsampleItem],
    probes: list[QueryProbe],
) -> TrialResult:
    """Run one (benchmark, N, condition) trial. Loads subsample → evaluates."""
    sub_items, sub_probes = subsample(items, probes, n, n_queries, seed)
    if not sub_probes:
        raise RuntimeError(
            f"no valid queries after subsample n={n} for benchmark {benchmark}"
        )
    print(
        f"  [{benchmark} n={n} cond={condition} seed={seed}] "
        f"items={len(sub_items)} probes={len(sub_probes)}"
    )
    saved_env = apply_condition(condition)
    try:
        r1, r10, mrr, wall_per_q, rss_peak_mb = _load_subsample_into_db(
            db_url, benchmark, sub_items, condition, sub_probes
        )
    finally:
        restore_env(saved_env)
    print(
        f"    r@1={r1:.3f} r@10={r10:.3f} mrr={mrr:.3f} "
        f"({wall_per_q:.1f}ms/q rss_peak={rss_peak_mb:.1f}MB)"
    )
    return TrialResult(
        benchmark=benchmark,
        n=n,
        condition=condition,
        seed=seed,
        n_queries=len(sub_probes),
        r_at_1=r1,
        r_at_10=r10,
        mrr=mrr,
        wall_per_query_ms=wall_per_q,
        rss_peak_mb=rss_peak_mb,
    )


# ── Output ──────────────────────────────────────────────────────────────


def _save_trial(out_dir: Path, result: TrialResult) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.benchmark}_{result.n}_{result.condition}.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "benchmark": result.benchmark,
        "n": result.n,
        "condition": result.condition,
        "seed": result.seed,
        "n_queries": result.n_queries,
        "r_at_1": round(result.r_at_1, 6),
        "r_at_10": round(result.r_at_10, 6),
        "mrr": round(result.mrr, 6),
        "wall_per_query_ms": round(result.wall_per_query_ms, 3),
        "rss_peak_mb": round(result.rss_peak_mb, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def _write_summary_csv(out_dir: Path, results: list[TrialResult]) -> Path:
    path = out_dir / "summary.csv"
    cols = [
        "benchmark",
        "n",
        "condition",
        "n_queries",
        "r_at_1",
        "r_at_10",
        "mrr",
        "wall_per_query_ms",
        "rss_peak_mb",
        "seed",
    ]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            w.writerow(
                [
                    r.benchmark,
                    r.n,
                    r.condition,
                    r.n_queries,
                    r.r_at_1,
                    r.r_at_10,
                    r.mrr,
                    r.wall_per_query_ms,
                    r.rss_peak_mb,
                    r.seed,
                ]
            )
    return path


# ── CLI ─────────────────────────────────────────────────────────────────


def _quick_clamp(n_values: list[int], queries: int) -> tuple[list[int], int]:
    """In quick mode, cap N to 100 and queries to 10."""
    return [min(n_values[0], 100)], min(10, queries)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmark", choices=SUPPORTED_BENCHMARKS, required=True)
    p.add_argument("--n", type=int, nargs="+", required=True)
    p.add_argument("--queries", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--db-url", default=DEFAULT_DB_URL)
    args = p.parse_args()
    benchmark = args.benchmark
    n_values = list(args.n)
    n_queries = args.queries
    if args.quick:
        n_values, n_queries = _quick_clamp(n_values, n_queries)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / timestamp
    print(
        f"== e2_subsample :: bench={benchmark} n={n_values} queries={n_queries} "
        f"seed={args.seed} quick={args.quick} =="
    )
    print(f"   db_url={args.db_url} output_dir={out_dir.relative_to(_ROOT)}")
    print(f"   loading {benchmark} corpus + probes ...")
    items, probes = LOADERS[benchmark](args.seed)
    print(f"   loaded items={len(items)} probes={len(probes)}")
    results: list[TrialResult] = []
    for n in n_values:
        for cond in CONDITIONS:
            try:
                r = run_trial(
                    benchmark, n, cond, args.seed, n_queries, args.db_url, items, probes
                )
            except Exception as exc:
                print(f"  [{benchmark} n={n} cond={cond}] FAILED: {exc!r}")
                continue
            saved_path = _save_trial(out_dir, r)
            print(f"    -> {saved_path.relative_to(_ROOT)}")
            results.append(r)
    if results:
        csv_path = _write_summary_csv(out_dir, results)
        print(f"summary: {csv_path.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
