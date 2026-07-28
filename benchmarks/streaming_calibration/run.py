"""Streaming-ingest calibration sweep (sharded-popping-harbor, Phase B).

Measures the staging-sink write-latency / throughput curve across batch sizes
so the streaming constants are MEASURED, not invented (zetetic §4). Derives:

  - row_bytes  — in-Python size of one row (for the RAM invariant Q_cap).
  - B_max      — largest batch whose p99 write latency stays <= W_target.
  - B_min      — smallest batch before per-row fixed overhead collapses rows/s.
  - W_target   — the p99 latency of the proven 1000-row chunk (the SLO anchor).

It also answers the design question: is adaptive (AIMD) batch sizing justified,
or is a fixed chunk near-optimal across the swept range? If throughput is flat
past some knee, fixed wins (YAGNI) and the AdaptiveBatchController is not needed.

Run:  python benchmarks/streaming_calibration/run.py [--url postgresql://localhost:5432/cortex_calib]

Writes results to benchmarks/streaming_calibration/results.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.infrastructure.staging_resolve_sink import (  # noqa: E402
    build_edge_sink,
    build_entity_sink,
)

SIZES = [100, 200, 500, 1000, 2000, 5000, 10000]
BATCHES_PER_SIZE = 20  # timed batches after a warmup batch
_MIGRATIONS = [
    "CREATE INDEX IF NOT EXISTS idx_entities_lower_name ON entities (LOWER(name))",
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_indexes
                       WHERE indexname = 'uq_relationships_directed') THEN
            CREATE UNIQUE INDEX uq_relationships_directed
                ON relationships (source_entity_id, target_entity_id,
                                  relationship_type);
        END IF;
    END $$;""",
]


def _percentile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def _entity_rows(n: int, base: int) -> list[tuple]:
    return [(f"sym_{base + i}", "function", "calib", 1.0) for i in range(n)]


def _edge_rows(n: int, base: int) -> list[tuple]:
    # Every endpoint references an entity created in the entity sweep, so the
    # JOIN resolves (measures the resolve cost, not dangling-drop).
    return [
        (f"e_{(base + i) % 50000}", f"e_{(base + i + 1) % 50000}", "calls", 1.0)
        for i in range(n)
    ]


def _row_bytes(rows: list[tuple]) -> int:
    """Approximate in-Python bytes of one row (tuple + its str fields)."""
    if not rows:
        return 0
    r = rows[0]
    return sys.getsizeof(r) + sum(
        sys.getsizeof(v) for v in r if isinstance(v, (str, bytes))
    )


def _truncate(conn) -> None:
    conn.execute("TRUNCATE entities, relationships RESTART IDENTITY CASCADE")


def _sweep_entities(pool, url) -> list[dict]:
    out = []
    with psycopg.connect(url, autocommit=True) as conn:
        for size in SIZES:
            _truncate(conn)
            sink = build_entity_sink(pool.connection)
            base = 0
            sink.write_batch(_entity_rows(size, base))  # warmup
            base += size
            lat = []
            for _ in range(BATCHES_PER_SIZE):
                rows = _entity_rows(size, base)
                base += size
                t0 = time.perf_counter()
                sink.write_batch(rows)
                lat.append(time.perf_counter() - t0)
            sink.close()
            out.append(_stats("entity", size, lat, _row_bytes(_entity_rows(1, 0))))
    return out


def _sweep_edges(pool, url) -> list[dict]:
    out = []
    with psycopg.connect(url, autocommit=True) as conn:
        # Pre-create 50k entities so edges resolve via JOIN.
        _truncate(conn)
        esink = build_entity_sink(pool.connection)
        for b in range(0, 50000, 5000):
            esink.write_batch(
                [(f"e_{b + i}", "function", "calib", 1.0) for i in range(5000)]
            )
        esink.close()
        for size in SIZES:
            conn.execute("TRUNCATE relationships RESTART IDENTITY")
            sink = build_edge_sink(pool.connection)
            base = 0
            sink.write_batch(_edge_rows(size, base))  # warmup
            base += size
            lat = []
            for _ in range(BATCHES_PER_SIZE):
                rows = _edge_rows(size, base)
                base += size
                t0 = time.perf_counter()
                sink.write_batch(rows)
                lat.append(time.perf_counter() - t0)
            sink.close()
            out.append(_stats("edge", size, lat, _row_bytes(_edge_rows(1, 0))))
    return out


def _stats(kind: str, size: int, lat: list[float], row_bytes: int) -> dict:
    p50, p99 = _percentile(lat, 50), _percentile(lat, 99)
    rows_per_s = size / p50 if p50 > 0 else 0.0
    return {
        "kind": kind,
        "batch_size": size,
        "row_bytes": row_bytes,
        "p50_ms": round(p50 * 1000, 3),
        "p99_ms": round(p99 * 1000, 3),
        "rows_per_s": round(rows_per_s),
    }


def _derive(rows: list[dict], w_target_anchor: int = 1000) -> dict:
    by_size = {r["batch_size"]: r for r in rows}
    w_target = by_size[w_target_anchor]["p99_ms"] if w_target_anchor in by_size else 0.0
    under = [r["batch_size"] for r in rows if r["p99_ms"] <= w_target * 1.5]
    b_max = max(under) if under else w_target_anchor
    best_tput = max(rows, key=lambda r: r["rows_per_s"])
    # B_min: smallest size whose throughput is >= 50% of the best (below it,
    # per-row fixed overhead dominates).
    knee = [
        r["batch_size"]
        for r in rows
        if r["rows_per_s"] >= 0.5 * best_tput["rows_per_s"]
    ]
    b_min = min(knee) if knee else min(SIZES)
    return {
        "row_bytes": rows[0]["row_bytes"] if rows else 0,
        "w_target_ms": w_target,
        "b_min": b_min,
        "b_max": b_max,
        "best_throughput_size": best_tput["batch_size"],
        "best_rows_per_s": best_tput["rows_per_s"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="postgresql://localhost:5432/cortex_test")
    args = ap.parse_args()

    with psycopg.connect(args.url, autocommit=True) as conn:
        for stmt in _MIGRATIONS:
            conn.execute(stmt)

    pool = ConnectionPool(
        conninfo=args.url,
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "row_factory": psycopg.rows.dict_row},
        open=True,
    )
    try:
        ent = _sweep_entities(pool, args.url)
        edge = _sweep_edges(pool, args.url)
    finally:
        pool.close()

    result = {
        "sizes": SIZES,
        "batches_per_size": BATCHES_PER_SIZE,
        "entity": ent,
        "edge": edge,
        "derived": {"entity": _derive(ent), "edge": _derive(edge)},
    }
    out_path = Path(__file__).with_name("results.json")
    out_path.write_text(json.dumps(result, indent=2))

    print(
        f"{'kind':7} {'batch':>7} {'p50_ms':>9} {'p99_ms':>9} "
        f"{'rows/s':>10} {'row_B':>6}"
    )
    for r in ent + edge:
        print(
            f"{r['kind']:7} {r['batch_size']:>7} {r['p50_ms']:>9} {r['p99_ms']:>9} "
            f"{r['rows_per_s']:>10} {r['row_bytes']:>6}"
        )
    print("\nDerived constants (MEASURED):")
    for k, d in result["derived"].items():
        print(f"  {k}: {d}")
    print(f"\nresults → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
