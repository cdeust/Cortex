"""Longitudinal drip-feed harness.

Drip-feeds N synthetic memories spread uniformly across the past 365
days, then queries old vs recent facts at the current real wall-clock
time. Measures how cleanly the decay-aware retrieval pipeline preserves
recall as memories age.

Each memory has a deterministic ground-truth fact:
    "the chosen number for memory <uid> is <hash(uid) % 10000>"
The corresponding probe query asks the chosen-number for a given uid
and expects the seeded memory back at top-1.

Time injection strategy
-----------------------
The production write path stamps ``heat_base_set_at`` and
``last_accessed`` to ``NOW()`` on insert. To simulate a memory created
N days ago, we INSERT with a backdated ``created_at`` then UPDATE
``heat_base_set_at`` and ``last_accessed`` to match. The retrieval-time
``effective_heat()`` reads ``t_now - heat_base_set_at`` so this single
column is the load-bearing dial for decay age.

We use a dedicated database (default ``cortex_longitudinal_test``) to
avoid polluting production memory. The DB is dropped and recreated at
run start.

CLI:
    python -m benchmarks.lib.longitudinal_runner
    python -m benchmarks.lib.longitudinal_runner --quick
    python -m benchmarks.lib.longitudinal_runner --n-memories 100000 \\
        --queries-per-bucket 1000 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

import psycopg  # noqa: E402

RESULTS_ROOT = REPO_ROOT / "benchmarks" / "results" / "longitudinal"

# Bucket ages in days. Indexed at insertion + queried at run-time.
BUCKETS_DAYS = [30, 90, 180, 270, 360]
TAG = "longitudinal_test"


# ── Synthetic data generator ─────────────────────────────────────────────


def chosen_number(uid: int) -> int:
    """Deterministic ground-truth fact tied to a memory uid."""
    h = hashlib.sha256(f"longitudinal:{uid}".encode()).hexdigest()
    return int(h[:8], 16) % 10000


def memory_content(uid: int) -> str:
    return f"The chosen number for memory {uid} is {chosen_number(uid)}."


def query_for(uid: int) -> str:
    return f"What is the chosen number for memory {uid}?"


def assign_bucket(rng: random.Random, n_buckets: int) -> int:
    """Return one of the bucket indices uniformly."""
    return rng.randrange(n_buckets)


# ── DB lifecycle ─────────────────────────────────────────────────────────


def _admin_url(prod_url: str) -> str:
    """Switch a libpq URL to point at the maintenance DB ``postgres``."""
    parts = urlparse(prod_url)
    return urlunparse(parts._replace(path="/postgres"))


def reset_database(database_url: str, db_name: str) -> None:
    """Drop + recreate the longitudinal test DB."""
    admin_url = _admin_url(database_url)
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        conn.execute(f'CREATE DATABASE "{db_name}"')
    print(f"[long] reset DB: {db_name}")


def configure_environment(database_url: str, db_name: str) -> str:
    """Point CORTEX at the longitudinal DB for this process."""
    parts = urlparse(database_url)
    new_url = urlunparse(parts._replace(path=f"/{db_name}"))
    os.environ["DATABASE_URL"] = new_url
    return new_url


# ── Insertion path ───────────────────────────────────────────────────────


def _stamp_age(store, mem_ids: list[int], age_days: list[float]) -> None:
    """Backdate created_at / heat_base_set_at / last_accessed.

    age_days[i] is how many days ago memory mem_ids[i] should look. We
    issue one parameterised UPDATE per memory; for 100k rows this takes
    a few seconds but is bounded and deterministic.
    """
    rows = list(zip(mem_ids, age_days))
    sql = """
        UPDATE memories SET
            created_at = NOW() - (%s || ' days')::INTERVAL,
            heat_base_set_at = NOW() - (%s || ' days')::INTERVAL,
            last_accessed = NOW() - (%s || ' days')::INTERVAL
        WHERE id = %s
    """
    cur = store._conn.cursor()
    try:
        for mid, age in rows:
            age_str = f"{age:.6f}"
            cur.execute(sql, (age_str, age_str, age_str, mid))
        store._conn.commit()
    finally:
        cur.close()


def insert_memories(
    bench_db, n: int, rng: random.Random, n_buckets: int
) -> list[tuple[int, int, int]]:
    """Insert N memories with random uniform ages across 0–365 days.

    Returns list of (uid, memory_id, bucket_idx).
    """
    from benchmarks.beam.run_benchmark import run_benchmark  # noqa: F401

    print(f"[long] generating {n} synthetic memories…")
    payloads = []
    bucket_assignments: list[int] = []
    age_days: list[float] = []
    for uid in range(n):
        bucket = assign_bucket(rng, n_buckets)
        bucket_assignments.append(bucket)
        # Spread uniformly within the bucket's day range to avoid a spike
        center = BUCKETS_DAYS[bucket]
        jitter = rng.uniform(-15.0, 15.0)
        age = max(0.5, center + jitter)
        age_days.append(age)
        payloads.append(
            {
                "content": memory_content(uid),
                "tags": [TAG, f"bucket_{bucket}"],
                "source": "longitudinal",
                "created_at": (
                    datetime.now(timezone.utc) - timedelta(days=age)
                ).isoformat(),
            }
        )

    print("[long] inserting via ingest_memories_batch…")
    t0 = time.time()
    mem_ids, _ = bench_db.load_memories(
        payloads,
        domain="longitudinal",
        batch_embed=True,
        decompose=False,
    )
    print(f"[long] insert done ({time.time() - t0:.1f}s, {len(mem_ids)} rows)")

    print("[long] backdating heat_base_set_at to match created_at…")
    t0 = time.time()
    _stamp_age(bench_db._store, mem_ids, age_days)
    print(f"[long] backdate done ({time.time() - t0:.1f}s)")

    return [(uid, mid, b) for uid, mid, b in zip(range(n), mem_ids, bucket_assignments)]


# ── Query path ───────────────────────────────────────────────────────────


def evaluate_buckets(
    bench_db,
    triples: list[tuple[int, int, int]],
    queries_per_bucket: int,
    rng: random.Random,
    n_buckets: int,
) -> dict:
    """Sample N queries per bucket; measure R@1 and R@10."""
    by_bucket: dict[int, list[tuple[int, int]]] = {b: [] for b in range(n_buckets)}
    for uid, mid, b in triples:
        by_bucket[b].append((uid, mid))

    results: dict[int, dict] = {}
    for b, items in by_bucket.items():
        if not items:
            continue
        sample = (
            items
            if len(items) <= queries_per_bucket
            else rng.sample(items, queries_per_bucket)
        )
        hits1 = 0
        hits10 = 0
        latencies = []
        for uid, expected_id in sample:
            t0 = time.time()
            recalled = bench_db.recall(
                query_for(uid),
                top_k=10,
                domain="longitudinal",
                min_heat=0.0,
            )
            latencies.append(time.time() - t0)
            ranks = [r.get("memory_id") or r.get("id") for r in recalled]
            if ranks and ranks[0] == expected_id:
                hits1 += 1
            if expected_id in ranks:
                hits10 += 1
        total = len(sample)
        results[b] = {
            "age_days": BUCKETS_DAYS[b],
            "n_queries": total,
            "r_at_1": hits1 / total if total else 0.0,
            "r_at_10": hits10 / total if total else 0.0,
            "median_latency_ms": (
                sorted(latencies)[len(latencies) // 2] * 1000.0 if latencies else 0.0
            ),
        }
        print(
            f"[long] bucket age={BUCKETS_DAYS[b]:>3}d  R@1={results[b]['r_at_1']:.3f}  "
            f"R@10={results[b]['r_at_10']:.3f}  n={total}"
        )
    return results


# ── Main ─────────────────────────────────────────────────────────────────


def run(n_memories: int, queries_per_bucket: int, seed: int, quick: bool) -> Path:
    if quick:
        n_memories = min(n_memories, 5000)
        queries_per_bucket = min(queries_per_bucket, 100)
    print(
        f"[long] config: N={n_memories}  Q/bucket={queries_per_bucket}  "
        f"seed={seed}  quick={quick}"
    )

    rng = random.Random(seed)
    np.random.seed(seed)

    prod_url = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
    db_name = os.environ.get("CORTEX_LONGITUDINAL_DB", "cortex_longitudinal_test")
    reset_database(prod_url, db_name)
    configure_environment(prod_url, db_name)

    # Import AFTER env override so PgMemoryStore picks up the test DB.
    from benchmarks.lib.bench_db import BenchmarkDB

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_ROOT / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    n_buckets = len(BUCKETS_DAYS)
    with BenchmarkDB() as db:
        triples = insert_memories(db, n_memories, rng, n_buckets)
        bucket_results = evaluate_buckets(
            db,
            triples,
            queries_per_bucket,
            rng,
            n_buckets,
        )

    # Pass criterion: R@10 at 360d ≥ R@10 at 30d − 0.05.
    youngest = bucket_results.get(0, {}).get("r_at_10", 0.0)
    oldest = bucket_results.get(n_buckets - 1, {}).get("r_at_10", 0.0)
    passed = oldest >= youngest - 0.05

    payload = {
        "config": {
            "n_memories": n_memories,
            "queries_per_bucket": queries_per_bucket,
            "seed": seed,
            "quick": quick,
            "buckets_days": BUCKETS_DAYS,
        },
        "results": {str(b): r for b, r in bucket_results.items()},
        "pass_criterion": {
            "rule": "R@10(oldest) >= R@10(youngest) - 0.05",
            "youngest_r_at_10": youngest,
            "oldest_r_at_10": oldest,
            "delta": oldest - youngest,
            "passed": bool(passed),
        },
    }
    out_path = out_dir / "results.json"
    out_path.write_text(json.dumps(payload, indent=2))

    print(
        f"\n[long] pass criterion: oldest({oldest:.3f}) "
        f"vs youngest({youngest:.3f})  →  {'PASS' if passed else 'FAIL'}"
    )
    print(f"[long] results → {out_path}")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Longitudinal drip-feed harness")
    parser.add_argument("--n-memories", type=int, default=100_000)
    parser.add_argument("--queries-per-bucket", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--quick", action="store_true", help="N=5000, 100 queries/bucket"
    )
    args = parser.parse_args(argv)
    run(args.n_memories, args.queries_per_bucket, args.seed, args.quick)
    return 0


if __name__ == "__main__":
    sys.exit(main())
