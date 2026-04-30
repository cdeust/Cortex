"""Cross-benchmark generalization runner (Popper C5 verification).

Hypothesis (pre-registered):
    A configuration calibrated on LongMemEval-S generalizes to LoCoMo
    without retuning. Specifically: Phase-B (LongMemEval-tuned, applied
    AS-IS to LoCoMo) MRR ≥ 0.92 × Phase-C (LoCoMo-tuned ceiling) MRR.

Falsifier:
    Phase-B MRR < 0.92 × Phase-C MRR → the config overfits the
    calibration corpus; the cross-benchmark claim is rejected.

Knobs (load-bearing per benchmarks-detail.md and memory_config.py):
    - decay λ          → CORTEX_DECAY_LAMBDA / CORTEX_MEMORY_DECAY_FACTOR
    - heat-prior weight → CORTEX_MEMORY_WRRF_HEAT_WEIGHT
    - FlashRank top-K   → CORTEX_MEMORY_WRRF_CANDIDATE_MULTIPLIER

Grid: 3 × 3 × 3 = 27 cells (auditable).

Subprocess isolation per cell: each cell launches a fresh Python process
with the env-var override. Required because mcp_server.core.thermodynamics
reads CORTEX_DECAY_LAMBDA at import time (thermodynamics.py:49) and
get_memory_settings is lru_cache'd, so in-process env mutation does not
take effect. See benchmarks/lib/_xb_drivers.py for the driver.

CLI:
    python -m benchmarks.lib.cross_benchmark_runner [--quick] [--seed 42]
                                                    [--out-dir <path>]
                                                    [--lm-limit N] [--loc-limit N]

Outputs (under <out-dir>/<timestamp>/):
    calibration.json     — Phase A: full grid × LongMemEval, with MRR/R@10
    evaluation.json      — Phase B: Phase-A winner applied AS-IS to LoCoMo
    reference.json       — Phase C: full grid × LoCoMo (oracle ceiling)
    summary.md           — human-readable verdict
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GRID: dict[str, list[float | int]] = {
    "decay_lambda": [0.92, 0.95, 0.98],
    "heat_weight": [0.15, 0.30, 0.50],
    "rerank_topk_mult": [5, 10, 20],
}
PASS_RATIO = 0.92
DRIVER_MODULE = "benchmarks.lib._xb_drivers"


def _enumerate_grid() -> list[dict[str, float | int]]:
    return [
        {"decay_lambda": d, "heat_weight": h, "rerank_topk_mult": k}
        for d, h, k in itertools.product(
            GRID["decay_lambda"], GRID["heat_weight"], GRID["rerank_topk_mult"]
        )
    ]


def _cell_id(cell: dict[str, float | int]) -> str:
    return f"d{cell['decay_lambda']}_h{cell['heat_weight']}_k{cell['rerank_topk_mult']}"


def _env_for_cell(cell: dict[str, float | int], seed: int) -> dict[str, str]:
    env = os.environ.copy()
    env["CORTEX_DECAY_LAMBDA"] = str(cell["decay_lambda"])
    env["CORTEX_MEMORY_DECAY_FACTOR"] = str(cell["decay_lambda"])
    env["CORTEX_MEMORY_WRRF_HEAT_WEIGHT"] = str(cell["heat_weight"])
    env["CORTEX_MEMORY_WRRF_CANDIDATE_MULTIPLIER"] = str(cell["rerank_topk_mult"])
    env["PYTHONHASHSEED"] = str(seed)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["TOKENIZERS_PARALLELISM"] = "false"
    return env


def _run_cell(
    benchmark: str, data_path: str, cell: dict[str, float | int], seed: int, limit: int
) -> dict[str, Any]:
    """Run one grid cell in a clean subprocess. Returns metrics dict."""
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", DRIVER_MODULE, benchmark, data_path, str(limit)],
        env=_env_for_cell(cell, seed),
        capture_output=True,
        text=True,
        timeout=3600,
    )
    payload: dict[str, Any] = {
        "cell": cell,
        "cell_id": _cell_id(cell),
        "benchmark": benchmark,
        "wall_clock_s": time.time() - t0,
        "mrr": None,
        "recall_at_10": None,
    }
    if proc.returncode != 0:
        payload["error"] = proc.stderr[-2000:]
        return payload
    for line in proc.stdout.splitlines():
        if line.startswith("__JSON__"):
            payload.update(json.loads(line[len("__JSON__") :]))
            return payload
    payload["error"] = "no __JSON__ line in driver stdout"
    return payload


def _grid_run(
    label: str, benchmark: str, data_path: str, limit: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the grid against `benchmark`, return (all results, best-by-MRR)."""
    cells = _enumerate_grid()
    print(f"[{label}] {benchmark}: {len(cells)} cells (limit={limit})")
    results: list[dict[str, Any]] = []
    for i, cell in enumerate(cells, 1):
        print(f"  [{i:>2}/{len(cells)}] {_cell_id(cell)} ...", flush=True)
        r = _run_cell(benchmark, data_path, cell, seed, limit)
        msg = (
            f"MRR={r['mrr']:.3f}"
            if r.get("mrr") is not None
            else f"ERROR: {r.get('error', 'unknown')[:120]}"
        )
        print(f"    {msg}")
        results.append(r)
    valid = [r for r in results if r.get("mrr") is not None]
    if not valid:
        raise RuntimeError(f"[{label}] all cells failed")
    best = max(valid, key=lambda r: r["mrr"])
    print(f"[{label}] best: {best['cell_id']} MRR={best['mrr']:.3f}")
    return results, best


def _summary_md(
    winner: dict[str, Any],
    eval_b: dict[str, Any],
    ref_best: dict[str, Any],
    out_dir: Path,
    seed: int,
    limits: dict[str, int],
) -> str:
    b, c = eval_b.get("mrr"), ref_best.get("mrr")
    if b is None or c is None or c == 0:
        verdict, ratio_str = "INCONCLUSIVE", "N/A"
    else:
        ratio = b / c
        verdict = "PASS" if ratio >= PASS_RATIO else "FAIL"
        ratio_str = f"{ratio:.3f}"
    return "\n".join(
        [
            "# Cross-benchmark generalization (Popper C5)",
            "",
            f"- Run timestamp: {out_dir.name}",
            f"- Seed: {seed}",
            f"- LongMemEval limit: {limits['lm']}",
            f"- LoCoMo limit: {limits['loc']}",
            f"- Pass criterion: Phase-B MRR ≥ {PASS_RATIO} × Phase-C MRR",
            "",
            "## Phase A — Calibration winner (LongMemEval-S)",
            f"- Cell: `{winner['cell_id']}`",
            f"- MRR: {winner['mrr']:.3f}",
            f"- R@10: {winner.get('recall_at_10', 'N/A')}",
            "",
            "## Phase B — LongMemEval-tuned applied AS-IS to LoCoMo",
            f"- MRR: {b if b is not None else 'ERROR'}",
            f"- R@10: {eval_b.get('recall_at_10', 'N/A')}",
            "",
            "## Phase C — LoCoMo-tuned ceiling",
            f"- Best cell: `{ref_best['cell_id']}`",
            f"- MRR: {c if c is not None else 'ERROR'}",
            f"- R@10: {ref_best.get('recall_at_10', 'N/A')}",
            "",
            "## Verdict",
            f"- Ratio Phase-B / Phase-C: {ratio_str}",
            f"- **{verdict}**",
            "",
        ]
    )


def _write_artifacts(
    out_dir: Path,
    calibration: list[dict[str, Any]],
    winner: dict[str, Any],
    eval_b: dict[str, Any],
    reference: list[dict[str, Any]],
    ref_best: dict[str, Any],
    seed: int,
    limits: dict[str, int],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar = {
        "seed": seed,
        "limits": limits,
        "grid": GRID,
        "pass_ratio": PASS_RATIO,
        "timestamp": out_dir.name,
    }
    (out_dir / "calibration.json").write_text(
        json.dumps(
            {"sidecar": sidecar, "winner": winner, "cells": calibration}, indent=2
        )
    )
    (out_dir / "evaluation.json").write_text(
        json.dumps(
            {"sidecar": sidecar, "winner_cell": winner["cell"], "result": eval_b},
            indent=2,
        )
    )
    (out_dir / "reference.json").write_text(
        json.dumps({"sidecar": sidecar, "best": ref_best, "cells": reference}, indent=2)
    )
    (out_dir / "summary.md").write_text(
        _summary_md(winner, eval_b, ref_best, out_dir, seed, limits)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Tiny limits (lm=20, loc=2 conv) for smoke-tests",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=str, default=None)
    parser.add_argument("--lm-limit", type=int, default=200)
    parser.add_argument("--loc-limit", type=int, default=10)
    args = parser.parse_args()

    if args.quick:
        args.lm_limit, args.loc_limit = 20, 2

    repo = Path(__file__).resolve().parents[2]
    lm_path = str(repo / "benchmarks" / "longmemeval" / "longmemeval_s.json")
    loc_path = str(repo / "benchmarks" / "locomo" / "locomo10.json")
    for p in (lm_path, loc_path):
        if not Path(p).exists():
            print(f"ERROR: dataset missing: {p}", file=sys.stderr)
            return 2

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = (
        Path(args.out_dir)
        if args.out_dir
        else (repo / "benchmarks" / "results" / "cross_benchmark")
    )
    out_dir = out_root / timestamp
    limits = {"lm": args.lm_limit, "loc": args.loc_limit}

    calibration, winner = _grid_run(
        "Phase A", "longmemeval", lm_path, args.lm_limit, args.seed
    )
    print("[Phase B] Evaluating LongMemEval-tuned config on LoCoMo (no retune)")
    eval_b = _run_cell("locomo", loc_path, winner["cell"], args.seed, args.loc_limit)
    if eval_b.get("mrr") is not None:
        print(f"  MRR={eval_b['mrr']:.3f}, R@10={eval_b.get('recall_at_10', 0):.3f}")
    else:
        print(f"  ERROR: {eval_b.get('error', 'unknown')[:120]}")
    reference, ref_best = _grid_run(
        "Phase C", "locomo", loc_path, args.loc_limit, args.seed
    )
    _write_artifacts(
        out_dir, calibration, winner, eval_b, reference, ref_best, args.seed, limits
    )
    print(f"\nArtifacts written to: {out_dir}")
    print((out_dir / "summary.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
