"""Empirical noise-floor measurement for verification thresholds.

Runs the SAME benchmark config N times from the SAME DB snapshot and
reports per-metric mean, std, p95, range. The measured σ becomes the
'smallest detectable effect' threshold for ablation / N-scan / decay-
sweep experiments — anything within σ is statistical noise.

Source: Curie verification audit — "the smallest reportable effect must
exceed the empirical noise floor of the measurement apparatus" (Fisher,
*The Design of Experiments*, 1935; restated for benchmark harnesses in
docs/program/n-scan-spec.md §noise_floor).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from benchmarks.lib.ablation_runner import (  # noqa: E402
    BENCHMARK_IDS,
    run_one,
)
from benchmarks.lib.db_snapshot import (  # noqa: E402
    fingerprint,
    restore_snapshot,
)
from benchmarks.lib import db_setup  # noqa: E402

RESULTS_DIR = _ROOT / "benchmarks" / "results" / "noise_floor"
# source: spec §Deliverable 3 — "smallest detectable effect" defined as
# 2σ following the standard 95% confidence threshold (Fisher 1935).
SDE_SIGMA_MULTIPLIER = 2.0


@dataclass
class RunSample:
    """Single rerun outcome."""

    r_at_10: float
    mrr: float
    n_queries: int
    wall_seconds: float


def _stats(samples: list[float]) -> dict[str, float]:
    """Return summary stats for a list of samples (n>=1)."""
    n = len(samples)
    mean = statistics.fmean(samples)
    std = statistics.stdev(samples) if n >= 2 else 0.0
    p95 = sorted(samples)[max(0, math.ceil(0.95 * n) - 1)]
    return {
        "mean": round(mean, 6),
        "std": round(std, 6),
        "min": round(min(samples), 6),
        "max": round(max(samples), 6),
        "p95": round(p95, 6),
        "samples": [round(s, 6) for s in samples],
    }


def _restore_target(snapshot_path: Path, target_db_url: str, *, run_id: str) -> None:
    """Restore + apply deterministic config (playbook §4.3, §4.10)."""
    report = restore_snapshot(target_db_url, snapshot_path)
    if not report.success:
        msg = "; ".join(report.mismatch + report.version_drift)
        raise RuntimeError(f"snapshot restore failed: {msg}")
    db_setup.apply_deterministic_database(target_db_url, run_id=run_id)
    db_setup.analyze_after_restore(target_db_url)


def _run_once(
    benchmark: str, target_db_url: str, quick: bool, *, run_id: str
) -> RunSample:
    """Run one benchmark trial against target_db_url."""
    saved = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = target_db_url
    try:
        metrics, wall, _, _ = run_one(benchmark, None, quick=quick, run_id=run_id)
    finally:
        if saved is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved
    return RunSample(
        r_at_10=metrics.r_at_10,
        mrr=metrics.mrr,
        n_queries=metrics.n_queries,
        wall_seconds=wall,
    )


def measure_noise_floor(
    benchmark: str,
    snapshot_path: Path,
    target_db_url: str,
    *,
    n_reruns: int = 5,
    quick: bool = False,
) -> dict:
    """Run N reruns from a single snapshot; return NoiseFloorReport dict.

    Pre: benchmark in BENCHMARK_IDS; snapshot_path + sidecar meta exist;
    target_db_url is benchmark-only (refuses prod via safety_guard inside
    restore_snapshot). Post: dict with per-metric mean/std/p95 + samples;
    smallest_detectable_effect = 2*std for each metric.
    """
    if benchmark not in BENCHMARK_IDS:
        raise ValueError(f"unknown benchmark: {benchmark}")
    if n_reruns < 2:
        raise ValueError("n_reruns must be >= 2 for std to be defined")
    sha = fingerprint(snapshot_path)
    samples: list[RunSample] = []
    for i in range(n_reruns):
        run_id = f"noise_{benchmark}_r{i + 1}"
        print(f"  [rerun {i + 1}/{n_reruns}] restoring snapshot ...")
        _restore_target(snapshot_path, target_db_url, run_id=run_id)
        print(f"  [rerun {i + 1}/{n_reruns}] running {benchmark} (quick={quick}) ...")
        t0 = time.monotonic()
        sample = _run_once(benchmark, target_db_url, quick, run_id=run_id)
        wall = time.monotonic() - t0
        print(
            f"  [rerun {i + 1}/{n_reruns}] r@10={sample.r_at_10:.4f} "
            f"mrr={sample.mrr:.4f} wall={wall:.1f}s"
        )
        samples.append(sample)
    r10 = _stats([s.r_at_10 for s in samples])
    mrr = _stats([s.mrr for s in samples])
    return {
        "benchmark": benchmark,
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": sha,
        "target_db_url": target_db_url,
        "n_reruns": n_reruns,
        "quick": quick,
        "metrics": {"r_at_10": r10, "mrr": mrr},
        "smallest_detectable_effect": {
            "r_at_10": round(SDE_SIGMA_MULTIPLIER * r10["std"], 6),
            "mrr": round(SDE_SIGMA_MULTIPLIER * mrr["std"], 6),
        },
        "n_queries": samples[0].n_queries if samples else 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _save(report: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sha8 = report["snapshot_sha256"][:8]
    path = RESULTS_DIR / f"{report['benchmark']}_{sha8}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmark", required=True, choices=BENCHMARK_IDS)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--target-db", required=True)
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--quick", action="store_true")
    args = p.parse_args()
    target_url = (
        args.target_db
        if "://" in args.target_db
        else f"postgresql://localhost:5432/{args.target_db}"
    )
    report = measure_noise_floor(
        args.benchmark,
        Path(args.snapshot),
        target_url,
        n_reruns=args.n,
        quick=args.quick,
    )
    out = _save(report)
    sde = report["smallest_detectable_effect"]
    print(f"\nnoise floor: {out.relative_to(_ROOT)}")
    print(
        f"  r@10: mean={report['metrics']['r_at_10']['mean']:.4f} "
        f"σ={report['metrics']['r_at_10']['std']:.4f} 2σ={sde['r_at_10']:.4f}"
    )
    print(
        f"  mrr:  mean={report['metrics']['mrr']['mean']:.4f} "
        f"σ={report['metrics']['mrr']['std']:.4f} 2σ={sde['mrr']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
