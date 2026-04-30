"""E2b — Synthetic corpus with Zipfian access patterns (E2 retrieval extension).

Extends E2 past N=1M where real benchmarks cap out. Generates N synthetic
memories in deterministic topic clusters, simulates K Zipfian access events
through the production read path (heat-update on access is exercised by
the same code that handles real recalls — never a direct heat assignment),
then evaluates queries biased toward high-access topics.

Sources:
  - Zipf, G. K. (1949). *Human Behavior and the Principle of Least Effort.*
    Addison-Wesley. — Word-frequency power law.
  - Mandelbrot, B. (1953). "An informational theory of the statistical
    structure of language." — Generalises Zipf; exponent alpha ~ 1.0–1.7
    calibrated for natural-language corpora; alpha=1.5 is the
    "natural-language" empirical default.

CLI: python -m benchmarks.lib.e2_zipf_runner --n N [N ...] --queries Q
     --access-events K --zipf-alpha 1.5 --seed 42 --db-url ... [--quick]
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

import numpy as np  # noqa: E402
from benchmarks.lib._e2_conditions import (  # noqa: E402
    CONDITIONS,
    apply_condition,
    heat_for,
    restore_env,
)
from benchmarks.lib.bench_db import BenchmarkDB  # noqa: E402

SCHEMA_VERSION = 1
RESULTS_DIR = _ROOT / "benchmarks" / "results" / "e2_zipf"
DEFAULT_DB_URL = "postgresql://localhost:5432/cortex_e2_zipf"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

# source: Mandelbrot 1953 — alpha~1.5 is the natural-language empirical default.
N_TOPICS = 50  # Topic count chosen so per-topic memory pool is non-trivial at N>=100.


@dataclass
class ZipfItem:
    memory: dict
    source_key: str
    topic_id: int


@dataclass
class TrialResult:
    n: int
    condition: str
    seed: int
    n_queries: int
    access_events: int
    zipf_alpha: float
    r_at_1: float
    r_at_10: float
    mrr: float
    wall_per_query_ms: float
    rss_peak_mb: float


def _topic_phrase(topic_id: int) -> str:
    return f"topic_{topic_id:03d}_subject"


def synth_corpus(n: int, seed: int, n_topics: int = N_TOPICS) -> list[ZipfItem]:
    """Generate N memories across n_topics with semantic continuity.

    Pre: n>=1, n_topics>=1. Post: list of length n; each item has topic_id
    in [0, n_topics); same-topic items share a phrase fragment so embeddings
    cluster.
    """
    rng = random.Random(seed)
    now = datetime.now(timezone.utc).isoformat()
    items: list[ZipfItem] = []
    for i in range(n):
        topic_id = rng.randrange(n_topics)
        sub_idx = rng.randrange(10_000)
        text = (
            f"Memory {i} on {_topic_phrase(topic_id)}: detail variant "
            f"{sub_idx} about subtopic-{topic_id}-{sub_idx % 7}."
        )
        key = f"zipf_{i}"
        items.append(
            ZipfItem(
                memory={
                    "content": text,
                    "user_content": text,
                    "source": key,
                    "tags": ["e2_zipf", f"topic_{topic_id:03d}"],
                    "created_at": now,
                },
                source_key=key,
                topic_id=topic_id,
            )
        )
    return items


def _zipf_indices(n: int, k: int, alpha: float, seed: int) -> np.ndarray:
    """Draw k indices in [0, n) from a Zipf(alpha) distribution.

    numpy.random.zipf samples from {1, 2, ...} on Z+. We clamp values to
    [1, n] and shift to [0, n-1]. A small minority of draws may exceed n
    (long tail); they are clamped to the largest valid index.
    """
    rng = np.random.default_rng(seed)
    raw = rng.zipf(alpha, size=k)
    clamped = np.clip(raw, 1, n) - 1
    return clamped.astype(np.int64)


def simulate_access(
    db: BenchmarkDB,
    items: list[ZipfItem],
    source_map: dict[int, str],
    access_events: int,
    alpha: float,
    seed: int,
    domain: str,
) -> None:
    """Drive K Zipfian accesses through the production read path.

    Each access calls db.recall() with the target item's content; this
    exercises the production write-back-on-access (heat update) without
    any direct heat assignment. Source: ADR-013 thermodynamic model —
    recall is the heat-update hook.
    """
    indices = _zipf_indices(len(items), access_events, alpha, seed)
    key_to_id = {v: k for k, v in source_map.items()}
    miss = 0
    for idx in indices.tolist():
        item = items[idx]
        if item.source_key not in key_to_id:
            miss += 1
            continue
        db.recall(item.memory["content"], top_k=10, domain=domain)
    if miss:
        print(f"    access-sim: {miss}/{len(indices)} items missing from source_map")


def make_queries(
    items: list[ZipfItem], n_queries: int, alpha: float, seed: int
) -> list[tuple[str, list[str]]]:
    """Sample queries biased toward high-access topics (Zipf over topics).

    Pre: items non-empty, n_queries>=1.
    Post: list of length <= n_queries where each entry is
    (query_text, target_source_keys) with at least one target key.
    """
    topics = sorted({it.topic_id for it in items})
    by_topic: dict[int, list[str]] = {t: [] for t in topics}
    for it in items:
        by_topic[it.topic_id].append(it.source_key)
    rng = np.random.default_rng(seed * 31 + 7)
    raw = np.clip(rng.zipf(alpha, size=n_queries * 3), 1, len(topics)) - 1
    out: list[tuple[str, list[str]]] = []
    for idx in raw.tolist():
        if len(out) >= n_queries:
            break
        topic_id = topics[idx]
        targets = by_topic[topic_id]
        if not targets:
            continue
        out.append((f"What do we know about {_topic_phrase(topic_id)}?", targets))
    return out


def evaluate(
    db: BenchmarkDB,
    queries: list[tuple[str, list[str]]],
    source_map: dict[int, str],
    domain: str,
) -> tuple[float, float, float, float]:
    """Return (r_at_1, r_at_10, mrr, wall_per_query_ms)."""
    hits1 = hits10 = 0
    rr_sum = 0.0
    wall_sum = 0.0
    for query, targets in queries:
        target_set = set(targets)
        t0 = time.monotonic()
        results = db.recall(query, top_k=10, domain=domain)
        wall_sum += (time.monotonic() - t0) * 1000.0
        retrieved_keys = [source_map.get(r["memory_id"], "") for r in results]
        rank = next(
            (i + 1 for i, k in enumerate(retrieved_keys) if k in target_set), None
        )
        if rank is not None:
            hits10 += 1
            rr_sum += 1.0 / rank
            if rank == 1:
                hits1 += 1
    n = max(1, len(queries))
    return hits1 / n, hits10 / n, rr_sum / n, wall_sum / n


def _execute_trial(
    items: list[ZipfItem],
    db_url: str,
    condition: str,
    seed: int,
    n_queries: int,
    access_events: int,
    zipf_alpha: float,
) -> tuple[float, float, float, float, float, int]:
    """Open DB, load, access-sim, evaluate. Returns (r1,r10,mrr,wall,rss_mb,n_q)."""
    saved_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    tracemalloc.start()
    try:
        with BenchmarkDB(database_url=db_url) as db:
            heat = heat_for(condition)
            payload = [{**it.memory, "heat": heat} for it in items]
            _, source_map = db.load_memories(payload, domain="e2_zipf")
            print(f"    simulating {access_events} Zipf({zipf_alpha}) accesses ...")
            simulate_access(
                db, items, source_map, access_events, zipf_alpha, seed, "e2_zipf"
            )
            queries = make_queries(items, n_queries, zipf_alpha, seed)
            print(f"    evaluating {len(queries)} queries ...")
            r1, r10, mrr, wall_per_q = evaluate(db, queries, source_map, "e2_zipf")
            n_q = len(queries)
    finally:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        if saved_db_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_db_url
    return r1, r10, mrr, wall_per_q, peak / (1024 * 1024), n_q


def run_trial(
    n: int,
    condition: str,
    seed: int,
    n_queries: int,
    access_events: int,
    zipf_alpha: float,
    db_url: str,
) -> TrialResult:
    """Run one (N, condition) trial: load → access-sim → evaluate."""
    items = synth_corpus(n, seed)
    print(f"  [n={n} cond={condition} seed={seed}] generated {len(items)} items")
    saved_env = apply_condition(condition)
    try:
        r1, r10, mrr, wall_per_q, rss_mb, n_q = _execute_trial(
            items, db_url, condition, seed, n_queries, access_events, zipf_alpha
        )
    finally:
        restore_env(saved_env)
    print(
        f"    r@1={r1:.3f} r@10={r10:.3f} mrr={mrr:.3f} "
        f"({wall_per_q:.1f}ms/q rss_peak={rss_mb:.1f}MB)"
    )
    return TrialResult(
        n=n,
        condition=condition,
        seed=seed,
        n_queries=n_q,
        access_events=access_events,
        zipf_alpha=zipf_alpha,
        r_at_1=r1,
        r_at_10=r10,
        mrr=mrr,
        wall_per_query_ms=wall_per_q,
        rss_peak_mb=rss_mb,
    )


def _save_trial(out_dir: Path, result: TrialResult) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.n}_{result.condition}.json"
    payload = {
        "schema_version": SCHEMA_VERSION,
        **{k: v for k, v in result.__dict__.items()},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
    }
    for f in ("r_at_1", "r_at_10", "mrr", "wall_per_query_ms", "rss_peak_mb"):
        payload[f] = round(payload[f], 6)
    path.write_text(json.dumps(payload, indent=2))
    return path


_SUMMARY_COLS = [
    "n",
    "condition",
    "n_queries",
    "access_events",
    "zipf_alpha",
    "r_at_1",
    "r_at_10",
    "mrr",
    "wall_per_query_ms",
    "rss_peak_mb",
    "seed",
]


def _write_summary_csv(out_dir: Path, results: list[TrialResult]) -> Path:
    path = out_dir / "summary.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_SUMMARY_COLS)
        for r in results:
            w.writerow([getattr(r, c) for c in _SUMMARY_COLS])
    return path


def _quick_clamp(
    n_values: list[int], queries: int, access_events: int
) -> tuple[list[int], int, int]:
    """Quick-mode caps: N=100, queries=10, access-events=200."""
    return [min(n_values[0], 100)], min(10, queries), min(200, access_events)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, nargs="+", required=True)
    p.add_argument("--queries", type=int, default=200)
    p.add_argument("--access-events", type=int, default=1000)
    p.add_argument("--zipf-alpha", type=float, default=1.5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--db-url", default=DEFAULT_DB_URL)
    args = p.parse_args()
    n_values = list(args.n)
    n_queries = args.queries
    access_events = args.access_events
    if args.quick:
        n_values, n_queries, access_events = _quick_clamp(
            n_values, n_queries, access_events
        )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_DIR / timestamp
    print(
        f"== e2_zipf :: n={n_values} queries={n_queries} "
        f"access_events={access_events} alpha={args.zipf_alpha} "
        f"seed={args.seed} quick={args.quick} =="
    )
    print(f"   db_url={args.db_url} output_dir={out_dir.relative_to(_ROOT)}")
    results: list[TrialResult] = []
    for n in n_values:
        for cond in CONDITIONS:
            try:
                r = run_trial(
                    n,
                    cond,
                    args.seed,
                    n_queries,
                    access_events,
                    args.zipf_alpha,
                    args.db_url,
                )
            except Exception as exc:
                print(f"  [n={n} cond={cond}] FAILED: {exc!r}")
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
