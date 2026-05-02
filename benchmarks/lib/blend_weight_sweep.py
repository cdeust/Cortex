"""Blend-weight calibration sweep for the 6 post-WRRF rerank stages.

Calibrates the engineering-default blend constants in
``mcp_server/core/recall_pipeline.py`` against LongMemEval-S so paper
§6.3 ships with cited optima rather than placeholders.

Methodology
-----------
Two-phase coordinate-descent (Fisher §Move 2):

* **Phase A** — central-composite design over the 4 perception-side knobs
  (HOPFIELD × HDC × SA × DENDRITIC). 17 cells = 1 center + 16 corners.
  Holds the affect-side knobs at their engineering default.
* **Phase B** — full 5×5 grid over the 2 affect-side knobs
  (EMOTIONAL_RETRIEVAL × MOOD_CONGRUENT) with the perception-side knobs
  fixed at the Phase A optimum.

A full 4-D 4-level grid would be 256 cells — infeasible at ~30 s/q × 100 q.
The CCD cuts 4-knob exploration to 17 cells while still admitting all
2-factor interaction effects within the design region. Source for CCD:
Box & Wilson (1951), *On the Experimental Attainment of Optimum
Conditions*, J. Royal Stat. Soc. B 13(1):1-45 — original central-composite
construction. We use the 2-level fractional-factorial face-centered
variant (no axial points beyond the corners) so all 17 cells remain on the
[0.10, 0.40] grid the engineering defaults already span.

Each cell runs in a fresh subprocess so the module-level reads in
``recall_pipeline.py`` pick up that cell's env vars cleanly. Cross-cell
state contamination is avoided by ``BenchmarkDB.clear()`` between
questions (already present in the runner).

Output
------
``benchmarks/results/blend_calibration/<timestamp>/``
  - ``cell_<idx>.json`` — per-cell {weights, mrr, r10, wall_seconds}
  - ``summary.csv``     — flat table for inspection
  - ``analysis.json``   — best cell + plateau width + per-knob marginal effect
  - ``manifest.json``   — code_hash, n_queries, phase, seed, total wall

Usage
-----
.. code-block:: bash

    # Phase A — 17 cells (CCD), n=50 questions
    python -m benchmarks.lib.blend_weight_sweep \\
      --phase a --n-queries 50

    # Phase B — 25 cells (full 5x5), n=30 questions, with Phase A optimum
    python -m benchmarks.lib.blend_weight_sweep \\
      --phase b --n-queries 30 \\
      --hopfield 0.30 --hdc 0.20 --sa 0.25 --dendritic 0.10

    # Smoke test — 3 cells only, n=5 questions
    python -m benchmarks.lib.blend_weight_sweep \\
      --phase smoke --n-queries 5

References
----------
- Box, G. E. P. & Wilson, K. B. (1951). Central-composite designs.
- Cormack, Clarke & Buettcher (2009). RRF blend constant k=60.
- ``tasks/verification-protocol.md`` — Fisher discipline for sweeps.
- ``tasks/blend-weight-calibration.md`` — pre-registration of THIS sweep.
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import os
import re
import subprocess
import sys
import time
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "benchmarks" / "results" / "blend_calibration"
LME_DATA = REPO_ROOT / "benchmarks" / "longmemeval" / "longmemeval_s.json"

# Engineering defaults (mirror of recall_pipeline.py — source of truth there).
DEFAULTS = {
    "HOPFIELD_BETA": 0.30,
    "HDC_BETA": 0.20,
    "SA_BETA": 0.25,
    "DENDRITIC_DELTA": 0.10,
    "EMOTIONAL_RETRIEVAL_BETA": 0.20,
    "MOOD_CONGRUENT_BETA": 0.15,
}

# Phase A central-composite design points.
# Center + 16 face-centered corners on [low, high] for each of 4 knobs.
# DENDRITIC uses a tighter range [0.05, 0.20] per the spec.
# source: tasks/blend-weight-calibration.md §Phase A grid.
PHASE_A_LOW = {"HOPFIELD_BETA": 0.10, "HDC_BETA": 0.10, "SA_BETA": 0.10, "DENDRITIC_DELTA": 0.05}
PHASE_A_HIGH = {"HOPFIELD_BETA": 0.40, "HDC_BETA": 0.40, "SA_BETA": 0.40, "DENDRITIC_DELTA": 0.20}
PHASE_A_CENTER = {"HOPFIELD_BETA": 0.30, "HDC_BETA": 0.20, "SA_BETA": 0.25, "DENDRITIC_DELTA": 0.10}

PHASE_B_GRID = {
    "EMOTIONAL_RETRIEVAL_BETA": [0.10, 0.15, 0.20, 0.25, 0.30],
    "MOOD_CONGRUENT_BETA": [0.05, 0.10, 0.15, 0.20, 0.25],
}


# ── Cell construction ───────────────────────────────────────────────────


@dataclass
class Cell:
    """One sweep cell: the 6 blend weights to apply for a single benchmark run."""

    idx: int
    label: str
    weights: dict[str, float]


def build_phase_a_cells() -> list[Cell]:
    """17 cells: 1 center + 16 corner points of the 4-knob CCD."""
    keys = ("HOPFIELD_BETA", "HDC_BETA", "SA_BETA", "DENDRITIC_DELTA")
    cells: list[Cell] = []
    cells.append(Cell(idx=0, label="A_center", weights={**DEFAULTS, **PHASE_A_CENTER}))
    for i, combo in enumerate(itertools.product([0, 1], repeat=4), start=1):
        weights = dict(DEFAULTS)
        for k, hl in zip(keys, combo):
            weights[k] = PHASE_A_HIGH[k] if hl else PHASE_A_LOW[k]
        label = "A_" + "".join("H" if hl else "L" for hl in combo)
        cells.append(Cell(idx=i, label=label, weights=weights))
    return cells


def build_phase_b_cells(perception_optimum: dict[str, float]) -> list[Cell]:
    """25 cells: full 5x5 over the 2 affect-side knobs at fixed perception optimum."""
    cells: list[Cell] = []
    idx = 0
    for er in PHASE_B_GRID["EMOTIONAL_RETRIEVAL_BETA"]:
        for mc in PHASE_B_GRID["MOOD_CONGRUENT_BETA"]:
            weights = {**DEFAULTS, **perception_optimum,
                       "EMOTIONAL_RETRIEVAL_BETA": er, "MOOD_CONGRUENT_BETA": mc}
            label = f"B_er{er:.2f}_mc{mc:.2f}"
            cells.append(Cell(idx=idx, label=label, weights=weights))
            idx += 1
    return cells


def build_smoke_cells() -> list[Cell]:
    """3 cells: low/center/high on HOPFIELD only — proves the env-var override fires."""
    return [
        Cell(idx=0, label="smoke_low",    weights={**DEFAULTS, "HOPFIELD_BETA": 0.10}),
        Cell(idx=1, label="smoke_center", weights={**DEFAULTS, "HOPFIELD_BETA": 0.30}),
        Cell(idx=2, label="smoke_high",   weights={**DEFAULTS, "HOPFIELD_BETA": 0.40}),
    ]


# ── Per-cell execution ──────────────────────────────────────────────────


def _cell_env(cell: Cell) -> dict[str, str]:
    """Build the env-var dict to inject for this cell."""
    env = dict(os.environ)
    for k, v in cell.weights.items():
        env[f"CORTEX_{k}"] = repr(float(v))
    return env


def run_cell(cell: Cell, n_queries: int, out_dir: Path) -> dict[str, Any]:
    """Run LongMemEval-S in a subprocess with this cell's env-var overrides.

    Returns: {idx, label, weights, mrr, r10, wall_seconds, returncode}.

    Subprocess isolation is mandatory: ``recall_pipeline.py`` reads its
    blend constants at module import time, so changing ``os.environ`` in
    the parent process AFTER the import would have no effect on later
    cells. One subprocess per cell guarantees a fresh import.
    """
    cmd = [
        sys.executable,
        str(REPO_ROOT / "benchmarks" / "longmemeval" / "run_benchmark.py"),
        "--variant", "s",
        "--limit", str(n_queries),
    ]
    env = _cell_env(cell)
    env["PYTHONHASHSEED"] = "0"
    env["CUDA_VISIBLE_DEVICES"] = ""
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd, env=env, cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=3600,
    )
    wall = time.monotonic() - t0
    metrics = _parse_lme_output(proc.stdout)
    record = {
        "idx": cell.idx,
        "label": cell.label,
        "weights": cell.weights,
        "n_queries": n_queries,
        "wall_seconds": wall,
        "returncode": proc.returncode,
        **metrics,
    }
    if proc.returncode != 0:
        # Persist the failure log alongside the cell record so a crashed
        # cell is investigated rather than silently averaged in.
        (out_dir / f"cell_{cell.idx:03d}_stderr.log").write_text(proc.stderr)
    (out_dir / f"cell_{cell.idx:03d}.json").write_text(json.dumps(record, indent=2))
    return record


_MRR_RE = re.compile(r"^MRR\s+([\d.]+)", re.MULTILINE)
_R10_RE = re.compile(r"^Recall@10\s+([\d.]+)%", re.MULTILINE)


def _parse_lme_output(stdout: str) -> dict[str, float | None]:
    """Pull MRR and R@10 out of the LongMemEval runner's printed table.

    The runner prints two lines:
        Recall@10                   97.8%       78.4%
        MRR                          0.882         --
    """
    mrr_m = _MRR_RE.search(stdout)
    r10_m = _R10_RE.search(stdout)
    return {
        "mrr": float(mrr_m.group(1)) if mrr_m else None,
        "r10": float(r10_m.group(1)) / 100.0 if r10_m else None,
    }


# ── Aggregation ─────────────────────────────────────────────────────────


def write_summary_csv(records: list[dict[str, Any]], out_dir: Path) -> None:
    """Write a flat CSV: one row per cell."""
    if not records:
        return
    fieldnames = ["idx", "label", "mrr", "r10", "n_queries", "wall_seconds", "returncode",
                  *(f"w_{k}" for k in DEFAULTS)]
    with (out_dir / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in records:
            row = {k: r.get(k) for k in ("idx", "label", "mrr", "r10",
                                         "n_queries", "wall_seconds", "returncode")}
            for k in DEFAULTS:
                row[f"w_{k}"] = r["weights"].get(k)
            w.writerow(row)


def analyze(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best cell by MRR (R@10 tiebreak), report plateau and per-knob effects."""
    valid = [r for r in records if r.get("mrr") is not None and r["returncode"] == 0]
    if not valid:
        return {"best": None, "note": "no valid cells"}
    best = max(valid, key=lambda r: (r["mrr"], r.get("r10") or 0.0))
    eps = 0.005  # MRR plateau half-width — within ±0.005 of best is "tied"
    plateau = [r for r in valid if abs(r["mrr"] - best["mrr"]) <= eps]
    marginal: dict[str, dict[str, float]] = {}
    for k in DEFAULTS:
        per_level: dict[float, list[float]] = {}
        for r in valid:
            per_level.setdefault(r["weights"][k], []).append(r["mrr"])
        if len(per_level) < 2:
            continue
        means = {lv: sum(xs) / len(xs) for lv, xs in per_level.items()}
        marginal[k] = {
            "range": max(means.values()) - min(means.values()),
            "best_level": max(means, key=means.get),
            "by_level": means,
        }
    return {
        "best": {"idx": best["idx"], "label": best["label"],
                 "weights": best["weights"], "mrr": best["mrr"], "r10": best["r10"]},
        "plateau_size": len(plateau),
        "plateau_eps": eps,
        "plateau_labels": [r["label"] for r in plateau],
        "marginal_effects": marginal,
    }


# ── Manifest ────────────────────────────────────────────────────────────


def write_manifest(out_dir: Path, args: argparse.Namespace, n_cells: int,
                   total_wall: float) -> None:
    """Emit the reproducibility manifest sidecar (Move 3)."""
    code_hash = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), text=True
    ).strip()
    # Dirtiness measured against TRACKED files only (matches the pre-registration
    # definition in tasks/blend-weight-calibration.md §Reproducibility manifest).
    # Untracked files (benchmark result archives, agent caches, node_modules) do
    # not contaminate the source tree being measured.
    dirty = bool(subprocess.check_output(
        ["git", "diff", "--stat", "HEAD"], cwd=str(REPO_ROOT), text=True
    ).strip())
    manifest = {
        "code_hash": code_hash,
        "dirty": dirty,
        "phase": args.phase,
        "n_queries": args.n_queries,
        "n_cells": n_cells,
        "total_wall_seconds": total_wall,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "command": sys.argv,
        "data_path": str(LME_DATA),
        "seed_note": "LongMemEval-S has fixed question order; benchmarks/lib/bench_db "
                     "applies CORTEX_BENCH_DETERMINISTIC_RUN_ID GUCs when set",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


# ── CLI ─────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--phase", choices=["a", "b", "smoke"], required=True)
    parser.add_argument("--n-queries", type=int, default=50)
    parser.add_argument("--hopfield", type=float, default=DEFAULTS["HOPFIELD_BETA"])
    parser.add_argument("--hdc", type=float, default=DEFAULTS["HDC_BETA"])
    parser.add_argument("--sa", type=float, default=DEFAULTS["SA_BETA"])
    parser.add_argument("--dendritic", type=float, default=DEFAULTS["DENDRITIC_DELTA"])
    parser.add_argument("--output", type=Path, default=None,
                        help="output dir; default benchmarks/results/blend_calibration/<ts>")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.output or (RESULTS_ROOT / ts)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.phase == "a":
        cells = build_phase_a_cells()
    elif args.phase == "b":
        perception = {
            "HOPFIELD_BETA": args.hopfield, "HDC_BETA": args.hdc,
            "SA_BETA": args.sa, "DENDRITIC_DELTA": args.dendritic,
        }
        cells = build_phase_b_cells(perception)
    else:
        cells = build_smoke_cells()

    print(f"[blend-sweep] phase={args.phase} cells={len(cells)} "
          f"n_queries={args.n_queries} out={out_dir}")
    t0 = time.monotonic()
    records: list[dict[str, Any]] = []
    for i, cell in enumerate(cells, start=1):
        cell_t0 = time.monotonic()
        rec = run_cell(cell, args.n_queries, out_dir)
        cell_dt = time.monotonic() - cell_t0
        ok = "OK" if rec["returncode"] == 0 and rec["mrr"] is not None else "FAIL"
        print(f"[blend-sweep] [{i}/{len(cells)}] {cell.label:24s} "
              f"mrr={rec.get('mrr')!s:>6} r10={rec.get('r10')!s:>6} "
              f"wall={cell_dt:6.1f}s {ok}")
        records.append(rec)
    total_wall = time.monotonic() - t0

    write_summary_csv(records, out_dir)
    analysis = analyze(records)
    (out_dir / "analysis.json").write_text(json.dumps(analysis, indent=2))
    write_manifest(out_dir, args, len(cells), total_wall)

    print(f"\n[blend-sweep] complete; wall={total_wall:.1f}s")
    if analysis.get("best"):
        b = analysis["best"]
        print(f"[blend-sweep] best cell: {b['label']} mrr={b['mrr']} r10={b['r10']}")
        print(f"[blend-sweep] plateau size: {analysis['plateau_size']} "
              f"(eps={analysis['plateau_eps']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
