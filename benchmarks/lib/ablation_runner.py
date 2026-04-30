"""Ablation runner for the Cortex verification campaign.

Drives the existing benchmarks (longmemeval-s, locomo, beam-100K) with one
mechanism disabled at a time. Two channels: CORTEX_ABLATE_<NAME>=1 env var
(always set) and monkey-patching neutral helpers from core.ablation.
Results land under benchmarks/results/ablation/<benchmark>/<mech>.json.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import tracemalloc
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Project root must be importable.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp_server.core import ablation as _ablation  # noqa: E402
from mcp_server.core.ablation import Mechanism  # noqa: E402
from benchmarks.lib.db_snapshot import (  # noqa: E402
    fingerprint,
    restore_snapshot,
)
from benchmarks.lib import db_setup  # noqa: E402

RESULTS_DIR = _ROOT / "benchmarks" / "results" / "ablation"
QUICK_LIMIT = 20  # source: smoke-test default; matches deliverable spec.
# source: spec §Deliverable 3 (HNSW determinism follow-up) — schema v3 adds
# settings_drift + db_setup fields populated alongside db_seed.
RESULT_SCHEMA_VERSION = 3

# Benchmark IDs accepted on the CLI and their dispatch metadata.
BENCHMARK_IDS = ("longmemeval-s", "locomo", "beam-100K")


# ── Result schema ────────────────────────────────────────────────────────


@dataclass
class BenchMetrics:
    """Single-run benchmark metrics."""

    r_at_10: float
    mrr: float
    n_queries: int


# ── Monkey-patch table ──────────────────────────────────────────────────
# Maps a Mechanism to a list of (module_path, attribute, replacement_fn).
# Replacement is a *factory* taking no args and returning a callable so
# each apply gets a fresh closure. Empty list = env-var-only (no patch).
#
# Only mechanisms with a known neutral function are wired. Others rely on
# the CORTEX_ABLATE_<NAME>=1 env var which is always set.

PatchSpec = tuple[str, str, Callable[[], Callable]]


def _patches_for(mech: Mechanism) -> list[PatchSpec]:
    """Return monkey-patch specs for a mechanism, or []."""
    no_decay: PatchSpec = (
        "mcp_server.core.thermodynamics",
        "compute_decay",
        lambda: lambda current_heat, *a, **k: current_heat,
    )
    table: dict[Mechanism, list[PatchSpec]] = {
        Mechanism.OSCILLATORY_CLOCK: [no_decay],
        Mechanism.ADAPTIVE_DECAY: [no_decay],
        Mechanism.HOMEOSTATIC_PLASTICITY: [
            (
                "mcp_server.core.ablation",
                "neutral_scaling_factor",
                lambda: _ablation.neutral_scaling_factor,
            )
        ],
    }
    return table.get(mech, [])


# ── Patch lifecycle ─────────────────────────────────────────────────────


def _apply_patches(specs: list[PatchSpec]) -> list[tuple[str, str, object]]:
    """Apply monkey-patches; return list of (module, attr, original) for restore."""
    saved: list[tuple[str, str, object]] = []
    for module_path, attr, factory in specs:
        mod = __import__(module_path, fromlist=[attr])
        original = getattr(mod, attr)
        saved.append((module_path, attr, original))
        setattr(mod, attr, factory())
    return saved


def _restore_patches(saved: list[tuple[str, str, object]]) -> None:
    for module_path, attr, original in saved:
        mod = __import__(module_path, fromlist=[attr])
        setattr(mod, attr, original)


# ── Stdout parser (works for all three benchmark scripts) ───────────────

_RE_R10 = re.compile(r"^Recall@10\s+(\d+\.\d+)%", re.MULTILINE)
_RE_MRR_LINE = re.compile(r"^MRR\s+(\d+\.\d+)", re.MULTILINE)
_RE_OVERALL = re.compile(
    r"^OVERALL\s+(\d+\.\d+)\s+(\d+\.\d+)%\s+(\d+\.\d+)%\s+(\d+)",
    re.MULTILINE,
)
_RE_QUESTIONS = re.compile(r"^Questions:\s+(\d+)", re.MULTILINE)


def _parse_metrics(stdout: str) -> BenchMetrics:
    """Extract R@10, MRR, n_queries from benchmark stdout.

    Pre: stdout has 'Recall@10 X%'+'MRR Y' (longmemeval) OR an
    'OVERALL MRR R@5 R@10 Qs' line. Post: BenchMetrics; missing -> 0.
    """
    r10 = mrr = 0.0
    n = 0
    if m := _RE_R10.search(stdout):
        r10 = float(m.group(1)) / 100.0
    if m := _RE_MRR_LINE.search(stdout):
        mrr = float(m.group(1))
    if m := _RE_OVERALL.search(stdout):
        mrr = float(m.group(1))
        r10 = float(m.group(3)) / 100.0
        n = int(m.group(4))
    if n == 0 and (m := _RE_QUESTIONS.search(stdout)):
        n = int(m.group(1))
    return BenchMetrics(r_at_10=r10, mrr=mrr, n_queries=n)


# ── Benchmark dispatch ──────────────────────────────────────────────────


def _resolve_benchmark(bench_id: str, quick: bool) -> tuple[Callable[[], None], int]:
    """Return (callable that runs the benchmark, declared n_queries-or-0)."""
    if bench_id == "longmemeval-s":
        from benchmarks.longmemeval.run_benchmark import run_benchmark as r

        data_path = _ROOT / "benchmarks" / "longmemeval" / "longmemeval_s.json"
        limit = QUICK_LIMIT if quick else 0
        return (lambda: r(str(data_path), limit=limit, verbose=False), limit)
    if bench_id == "locomo":
        from benchmarks.locomo.run_benchmark import run_benchmark as r

        data_path = _ROOT / "benchmarks" / "locomo" / "locomo10.json"
        limit = max(1, QUICK_LIMIT // 10) if quick else None
        return (lambda: r(str(data_path), limit=limit, verbose=False), limit or 0)
    if bench_id == "beam-100K":
        from benchmarks.beam.run_benchmark import run_benchmark as r

        limit = max(1, QUICK_LIMIT // 10) if quick else None
        return (lambda: r(split="100K", limit=limit, verbose=False), limit or 0)
    raise ValueError(f"unknown benchmark: {bench_id}")


# ── Run one trial ───────────────────────────────────────────────────────


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _set_ablation_env(mech: Mechanism | None) -> dict[str, str | None]:
    """Set CORTEX_ABLATE_<NAME>=1 (returns saved env state for restore)."""
    if mech is None:
        return {}
    key = f"CORTEX_ABLATE_{mech.name}"
    saved = {key: os.environ.get(key)}
    os.environ[key] = "1"
    return saved


def _restore_env(saved: dict[str, str | None]) -> None:
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def run_one(
    benchmark: str,
    mechanism: Mechanism | None,
    *,
    quick: bool,
    run_id: str | None = None,
) -> tuple[BenchMetrics, float, float, str]:
    """Run a single (benchmark, mechanism) trial.

    Pre: benchmark in BENCHMARK_IDS; mechanism is Mechanism or None
    (None=baseline). Post: (metrics, wall_s, rss_peak_mb, raw_stdout);
    env vars and monkey patches reverted before return. If run_id is
    given, BenchmarkDB picks up CORTEX_BENCH_DETERMINISTIC_RUN_ID and
    applies db_setup.apply_deterministic_session per playbook §8.
    """
    runner_fn, _ = _resolve_benchmark(benchmark, quick)
    patches = _patches_for(mechanism) if mechanism else []
    saved_env = _set_ablation_env(mechanism)
    saved_run_id = os.environ.get("CORTEX_BENCH_DETERMINISTIC_RUN_ID")
    if run_id is not None:
        os.environ["CORTEX_BENCH_DETERMINISTIC_RUN_ID"] = run_id
    saved_patches = _apply_patches(patches)
    buf = io.StringIO()
    tracemalloc.start()
    t0 = time.monotonic()
    try:
        with redirect_stdout(buf):
            runner_fn()
    finally:
        wall = time.monotonic() - t0
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        _restore_patches(saved_patches)
        _restore_env(saved_env)
        if saved_run_id is None:
            os.environ.pop("CORTEX_BENCH_DETERMINISTIC_RUN_ID", None)
        else:
            os.environ["CORTEX_BENCH_DETERMINISTIC_RUN_ID"] = saved_run_id
    metrics = _parse_metrics(buf.getvalue())
    return metrics, wall, peak / (1024 * 1024), buf.getvalue()


# ── Result IO ───────────────────────────────────────────────────────────


def _result_path(benchmark: str, mechanism: Mechanism | None) -> Path:
    name = "BASELINE" if mechanism is None else mechanism.name
    return RESULTS_DIR / benchmark / f"{name}.json"


def _save(
    benchmark: str,
    mechanism: Mechanism | None,
    metrics: BenchMetrics,
    baseline: BenchMetrics | None,
    wall: float,
    rss_mb: float,
    db_seed: dict | str = "not-snapshotted",
) -> Path:
    path = _result_path(benchmark, mechanism)
    path.parent.mkdir(parents=True, exist_ok=True)
    base_dict = (
        {"r_at_10": baseline.r_at_10, "mrr": baseline.mrr}
        if baseline is not None
        else {"r_at_10": metrics.r_at_10, "mrr": metrics.mrr}
    )
    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "mechanism": mechanism.name if mechanism else "BASELINE",
        "benchmark": benchmark,
        "n_queries": metrics.n_queries,
        "baseline": base_dict,
        "ablated": {"r_at_10": metrics.r_at_10, "mrr": metrics.mrr},
        "delta": {
            "r_at_10": round(metrics.r_at_10 - base_dict["r_at_10"], 6),
            "mrr": round(metrics.mrr - base_dict["mrr"], 6),
        },
        "wall_seconds": round(wall, 3),
        "rss_peak_mb": round(rss_mb, 3),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_dim": 384,
        # source: spec §Deliverable 2 — db_seed becomes a dict with
        # snapshot sha256 + meta when --from-snapshot is used.
        "db_seed": db_seed,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def _load_baseline(benchmark: str) -> BenchMetrics | None:
    path = _result_path(benchmark, None)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    a = data["ablated"]
    return BenchMetrics(r_at_10=a["r_at_10"], mrr=a["mrr"], n_queries=data["n_queries"])


# ── CLI ─────────────────────────────────────────────────────────────────


def _select_mechanisms(args: argparse.Namespace) -> list[Mechanism]:
    if args.all:
        return list(Mechanism)
    if not args.mechanism:
        return []
    out: list[Mechanism] = []
    for name in args.mechanism:
        try:
            out.append(Mechanism[name])
        except KeyError:
            raise SystemExit(f"unknown mechanism: {name}")
    return out


def _maybe_restore(
    snapshot_path: Path | None,
    target_db_url: str | None,
    *,
    run_id: str = "ablation",
) -> dict | str:
    """Restore snapshot (if any), apply deterministic DB+session config,
    ANALYZE, return db_seed payload (playbook §4.3, §4.10, §4.15)."""
    if snapshot_path is None or target_db_url is None:
        return "not-snapshotted"
    sha = fingerprint(snapshot_path)
    print(
        f"  [snapshot] restoring {snapshot_path.name} (sha8={sha[:8]}) -> "
        f"{target_db_url} ..."
    )
    report = restore_snapshot(target_db_url, snapshot_path)
    if not report.success:
        msg = "; ".join(report.mismatch + report.version_drift)
        raise RuntimeError(f"snapshot restore failed: {msg}")
    os.environ["DATABASE_URL"] = target_db_url
    # Post-restore deterministic setup (playbook §8 SRP split).
    db_applied = db_setup.apply_deterministic_database(target_db_url, run_id=run_id)
    db_setup.analyze_after_restore(target_db_url)
    meta_file = snapshot_path.with_suffix(snapshot_path.suffix + ".meta.json")
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    return {
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": sha,
        "target_db_url": target_db_url,
        "pg_version": meta.get("pg_version", "unknown"),
        "pgvector_version": meta.get("pgvector_version", "unknown"),
        "pg_server_version_num": meta.get("pg_server_version_num"),
        "pg_locale_collate": meta.get("pg_locale_collate"),
        "n_memories": meta.get("n_memories", report.n_memories_actual),
        "restore_wall_s": round(report.wall_seconds, 3),
        "version_drift": report.version_drift,
        "settings_drift": {k: list(v) for k, v in report.settings_drift.items()},
        "db_setup_applied": db_applied.applied,
        "db_setup_skipped": db_applied.skipped_due_to_permissions,
    }


def _run_baseline_if_needed(
    benchmark: str,
    quick: bool,
    force: bool,
    snapshot: Path | None,
    target_db: str | None,
) -> BenchMetrics:
    cached = None if force else _load_baseline(benchmark)
    if cached is not None:
        print(f"  [baseline] cached r@10={cached.r_at_10:.3f} mrr={cached.mrr:.3f}")
        return cached
    print(f"  [baseline] running ({benchmark}, quick={quick}) ...")
    run_id = f"{benchmark}_BASELINE"
    db_seed = _maybe_restore(snapshot, target_db, run_id=run_id)
    metrics, wall, rss, _ = run_one(
        benchmark, None, quick=quick, run_id=run_id if snapshot else None
    )
    _save(benchmark, None, metrics, None, wall, rss, db_seed=db_seed)
    print(
        f"  [baseline] r@10={metrics.r_at_10:.3f} mrr={metrics.mrr:.3f} "
        f"wall={wall:.1f}s"
    )
    return metrics


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--benchmark", required=True, choices=BENCHMARK_IDS)
    p.add_argument("--mechanism", action="append", default=[])
    p.add_argument("--all", action="store_true")
    p.add_argument("--baseline-only", action="store_true")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--from-snapshot",
        dest="from_snapshot",
        default=None,
        help="path to a custom-format pg_dump; restored before each trial",
    )
    p.add_argument(
        "--target-db",
        dest="target_db",
        default=None,
        help="benchmark-only DB URL/name to restore the snapshot into",
    )
    args = p.parse_args()

    snapshot = Path(args.from_snapshot) if args.from_snapshot else None
    target_db = None
    if snapshot is not None:
        if not args.target_db:
            raise SystemExit("--from-snapshot requires --target-db")
        target_db = (
            args.target_db
            if "://" in args.target_db
            else f"postgresql://localhost:5432/{args.target_db}"
        )
    else:
        print(
            "WARNING: --from-snapshot not set; results lack DB-state determinism. "
            "HNSW non-determinism + ingest order will leak into the deltas."
        )

    print(f"== ablation runner :: benchmark={args.benchmark} quick={args.quick} ==")
    baseline = _run_baseline_if_needed(
        args.benchmark,
        args.quick,
        args.force,
        snapshot,
        target_db,
    )
    if args.baseline_only:
        return 0
    mechs = _select_mechanisms(args)
    if not mechs:
        print("no --mechanism / --all given; nothing to do beyond baseline.")
        return 0

    for mech in mechs:
        path = _result_path(args.benchmark, mech)
        if path.exists() and not args.force:
            print(f"  [{mech.name}] cached at {path.relative_to(_ROOT)} (use --force)")
            continue
        print(f"  [{mech.name}] running ...")
        try:
            run_id = f"{args.benchmark}_{mech.name}"
            db_seed = _maybe_restore(snapshot, target_db, run_id=run_id)
            metrics, wall, rss, _ = run_one(
                args.benchmark,
                mech,
                quick=args.quick,
                run_id=run_id if snapshot else None,
            )
        except Exception as exc:  # source: ablation must be fail-soft per mech
            print(f"  [{mech.name}] FAILED: {exc!r}")
            continue
        out = _save(args.benchmark, mech, metrics, baseline, wall, rss, db_seed=db_seed)
        print(
            f"  [{mech.name}] r@10={metrics.r_at_10:.3f} "
            f"(Δ={metrics.r_at_10 - baseline.r_at_10:+.3f}) "
            f"mrr={metrics.mrr:.3f} wall={wall:.1f}s -> "
            f"{out.relative_to(_ROOT)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
