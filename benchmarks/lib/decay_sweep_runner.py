"""Decay dose-response sweeper.

Sweeps the load-bearing decay constant ``p_factor`` in the SQL
``effective_heat()`` function across a range of values, runs the BEAM
benchmark for each, and reports the optimum + plateau width + sensitivity
slope on each side.

The load-bearing knob is the per-hour Ebbinghaus rate baked into
``effective_heat(memories, t_now, factor, p_factor)`` — see
``mcp_server/infrastructure/pg_schema.py:565``. Default is 0.99787
(== 0.95 per DAY converted to per-HOUR via 0.95^(1/24)).

We override it per iteration by issuing ``CREATE OR REPLACE FUNCTION``
DDL that re-defines the function's DEFAULT for ``p_factor``. All BEAM
recall paths call the function as ``effective_heat(m, NOW(), v_factor)``
(3-arg form, no explicit p_factor), so the function default fully drives
the decay rate during retrieval.

CLI:
    python -m benchmarks.lib.decay_sweep_runner --lambda 0.85 0.90 0.95
    python -m benchmarks.lib.decay_sweep_runner --lambda 0.95 1.00 --quick

Outputs:
    benchmarks/results/decay_sweep/<timestamp>/lambda_<value>.json
    benchmarks/results/decay_sweep/<timestamp>/summary.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: E402

RESULTS_ROOT = REPO_ROOT / "benchmarks" / "results" / "decay_sweep"


# ── DDL override ─────────────────────────────────────────────────────────


_PFACTOR_RE = re.compile(r"p_factor\s+REAL\s+DEFAULT\s+[\d.]+")


def _build_effective_heat_ddl(p_factor: float) -> str:
    """Re-emit canonical EFFECTIVE_HEAT_FN with overridden p_factor default.

    We substitute the DEFAULT clause on the canonical DDL string from
    pg_schema.py rather than duplicating the function body — this avoids
    semantic drift if the production formula ever changes.
    """
    from mcp_server.infrastructure.pg_schema import EFFECTIVE_HEAT_FN

    replaced = _PFACTOR_RE.sub(
        f"p_factor    REAL DEFAULT {p_factor!r}", EFFECTIVE_HEAT_FN, count=1
    )
    if replaced == EFFECTIVE_HEAT_FN:
        raise RuntimeError("Could not locate p_factor DEFAULT in EFFECTIVE_HEAT_FN")
    return replaced


def override_p_factor(p_factor: float) -> None:
    """Apply DDL to redefine effective_heat with new p_factor default."""
    store = PgMemoryStore()
    try:
        store._conn.execute(_build_effective_heat_ddl(p_factor))
        store._conn.commit()
        # Drop cached prepared plans referencing the old function.
        try:
            store._conn.execute("DEALLOCATE ALL")
            store._conn.commit()
        except Exception:
            pass
    finally:
        store.close()


def reset_p_factor() -> None:
    """Restore production default by re-applying the schema."""
    # Re-importing the schema module and applying EFFECTIVE_HEAT_FN
    # restores the canonical 0.99787 default.
    from mcp_server.infrastructure.pg_schema import EFFECTIVE_HEAT_FN

    store = PgMemoryStore()
    try:
        store._conn.execute(EFFECTIVE_HEAT_FN)
        store._conn.commit()
    finally:
        store.close()


# ── Benchmark runner ─────────────────────────────────────────────────────


def run_beam(quick: bool) -> dict:
    """Run BEAM benchmark in-process, capture stdout, parse OVERALL line.

    Returns: {"mrr": float, "r5": float, "r10": float, "abilities": {...}}
    """
    from benchmarks.beam.run_benchmark import run_benchmark

    buf = io.StringIO()
    limit = 3 if quick else None  # 3 conversations is enough to detect signal
    with redirect_stdout(buf):
        run_benchmark(split="100K", limit=limit, verbose=False)
    return _parse_beam_output(buf.getvalue())


def _parse_beam_output(out: str) -> dict:
    """Parse the printed BEAM table into structured metrics."""
    abilities: dict[str, dict] = {}
    overall = {"mrr": 0.0, "r5": 0.0, "r10": 0.0}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        name = parts[0]
        try:
            mrr = float(parts[1])
            r5 = float(parts[2].rstrip("%")) / 100.0
            r10 = float(parts[3].rstrip("%")) / 100.0
        except ValueError:
            continue
        if name == "OVERALL":
            overall = {"mrr": mrr, "r5": r5, "r10": r10}
        elif name in {
            "abstention",
            "contradiction_resolution",
            "event_ordering",
            "information_extraction",
            "instruction_following",
            "knowledge_update",
            "multi_hop_reasoning",
            "preference_following",
            "summarization",
            "temporal_reasoning",
        }:
            abilities[name] = {"mrr": mrr, "r5": r5, "r10": r10}
    return {"overall": overall, "abilities": abilities, "raw_output": out}


# ── Curve analysis ───────────────────────────────────────────────────────


def analyze_curve(points: list[tuple[float, float]]) -> dict:
    """Compute optimum λ, plateau (within 1% of optimum MRR), and slopes.

    points: list of (lambda, mrr) sorted by lambda.
    """
    if not points:
        return {
            "optimum_lambda": None,
            "optimum_mrr": 0.0,
            "plateau_lo": None,
            "plateau_hi": None,
            "slope_left": None,
            "slope_right": None,
        }
    pts = sorted(points)
    opt = max(pts, key=lambda p: p[1])
    opt_lambda, opt_mrr = opt
    threshold = opt_mrr * 0.99  # within 1%
    plateau = [lam for lam, mrr in pts if mrr >= threshold]
    plateau_lo = min(plateau) if plateau else opt_lambda
    plateau_hi = max(plateau) if plateau else opt_lambda
    # Sensitivity slopes: finite difference around the optimum
    idx = pts.index(opt)
    slope_left: float | None = None
    slope_right: float | None = None
    if idx > 0:
        lam_l, mrr_l = pts[idx - 1]
        denom = opt_lambda - lam_l
        slope_left = (opt_mrr - mrr_l) / denom if denom else None
    if idx < len(pts) - 1:
        lam_r, mrr_r = pts[idx + 1]
        denom = lam_r - opt_lambda
        slope_right = (mrr_r - opt_mrr) / denom if denom else None
    return {
        "optimum_lambda": opt_lambda,
        "optimum_mrr": opt_mrr,
        "plateau_lo": plateau_lo,
        "plateau_hi": plateau_hi,
        "plateau_width": plateau_hi - plateau_lo,
        "slope_left": slope_left,
        "slope_right": slope_right,
    }


# ── Main ─────────────────────────────────────────────────────────────────


def run_sweep(lambdas: list[float], quick: bool) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = RESULTS_ROOT / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[sweep] output → {out_dir}")
    print(f"[sweep] lambdas: {lambdas}  quick={quick}")

    points: list[tuple[float, float]] = []
    summary_rows = []
    try:
        for lam in lambdas:
            print(f"\n[sweep] λ={lam} — applying DDL override…")
            override_p_factor(lam)
            t0 = time.time()
            try:
                metrics = run_beam(quick=quick)
            except Exception as exc:
                print(f"[sweep] λ={lam} FAILED: {exc!r}")
                metrics = {
                    "overall": {"mrr": 0.0, "r5": 0.0, "r10": 0.0},
                    "abilities": {},
                    "error": repr(exc),
                }
            elapsed = time.time() - t0
            mrr = metrics["overall"]["mrr"]
            r10 = metrics["overall"]["r10"]
            print(f"[sweep] λ={lam}  MRR={mrr:.3f}  R@10={r10:.3f}  ({elapsed:.1f}s)")
            payload = {
                "lambda": lam,
                "elapsed_seconds": elapsed,
                "quick": quick,
                "metrics": metrics,
            }
            (out_dir / f"lambda_{lam}.json").write_text(json.dumps(payload, indent=2))
            points.append((lam, mrr))
            summary_rows.append(
                {
                    "lambda": lam,
                    "mrr": mrr,
                    "r5": metrics["overall"]["r5"],
                    "r10": r10,
                    "elapsed_seconds": round(elapsed, 1),
                }
            )
    finally:
        print("\n[sweep] restoring production p_factor…")
        try:
            reset_p_factor()
        except Exception as exc:
            print(f"[sweep] WARN: reset failed: {exc!r}")

    analysis = analyze_curve(points)
    print("\n[sweep] curve analysis:")
    for k, v in analysis.items():
        print(f"  {k}: {v}")

    summary_csv = out_dir / "summary.csv"
    with summary_csv.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["lambda", "mrr", "r5", "r10", "elapsed_seconds"]
        )
        w.writeheader()
        w.writerows(summary_rows)
    (out_dir / "analysis.json").write_text(json.dumps(analysis, indent=2))
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decay dose-response sweep")
    parser.add_argument(
        "--lambda",
        dest="lambdas",
        nargs="+",
        type=float,
        required=True,
        help="One or more p_factor values (per-hour Ebbinghaus rate).",
    )
    parser.add_argument(
        "--benchmark",
        default="beam",
        choices=["beam"],
        help="Benchmark to drive (only beam wired).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Cap to 3 BEAM conversations for smoke testing.",
    )
    args = parser.parse_args(argv)

    out_dir = run_sweep(args.lambdas, quick=args.quick)
    print(f"\n[sweep] DONE → {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
