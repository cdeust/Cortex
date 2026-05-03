"""E1 v3 — LongMemEval-S per-mechanism ablation runner.

Drives `benchmarks/longmemeval/run_benchmark.py --variant s` once per row
(BASELINE + 16 mechanisms), serially, against the same PG instance. Each row
writes its result JSON via `--results-out`. After all rows complete, an
aggregate `summary.csv` and `manifest.json` are written.

Output: benchmarks/results/ablation/longmemeval-s_v3/

Why serial: the harness mutates a shared PG database (db.clear() per question).
Parallel rows would contaminate each other's haystacks.

Source / scope: task #54 — paper §6.3 read-path ablation evidence.
n=500 (full LME-S). Estimated wall ~11h. No --with-consolidation
(consolidation-only mechanisms are routed to LME-LoCoMo, task #55).
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OUT_DIR = _ROOT / "benchmarks" / "results" / "ablation" / "longmemeval-s_v3"
_HARNESS = _ROOT / "benchmarks" / "longmemeval" / "run_benchmark.py"

# 17 rows: BASELINE + 16 mechanisms.
# Read-path (8) + write-path-propagating (7) + newly-wired RECONSOLIDATION (1).
# MOOD_CONGRUENT_RERANK excluded (no-op until upstream classifier — task #54).
# SCHEMA_ENGINE + 8 consolidation-only mechs excluded (LoCoMo half — task #55).
MECHANISMS: list[str] = [
    # Read-path
    "HOPFIELD",
    "HDC",
    "SPREADING_ACTIVATION",
    "DENDRITIC_CLUSTERS",
    "EMOTIONAL_RETRIEVAL",
    "ADAPTIVE_DECAY",
    "CO_ACTIVATION",
    "SURPRISE_MOMENTUM",
    # Write-path propagating to retrieval
    "OSCILLATORY_CLOCK",
    "PREDICTIVE_CODING",
    "NEUROMODULATION",
    "PATTERN_SEPARATION",
    "EMOTIONAL_TAGGING",
    "SYNAPTIC_TAGGING",
    "ENGRAM_ALLOCATION",
    # Newly wired
    "RECONSOLIDATION",
]


def _git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=_ROOT
    )
    return out.stdout.strip()


def _git_dirty() -> bool:
    out = subprocess.run(
        ["git", "diff", "--stat", "--ignore-submodules=all", "HEAD"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    return bool(out.stdout.strip())


def _run_row(label: str, ablate: str | None) -> dict:
    """Run one row. label is the filename stem; ablate is None for BASELINE."""
    out_path = _OUT_DIR / f"{label}.json"
    cmd = [
        "uv",
        "run",
        "python",
        str(_HARNESS),
        "--variant",
        "s",
        "--results-out",
        str(out_path),
    ]
    if ablate is not None:
        cmd += ["--ablate", ablate]

    print(f"\n{'=' * 70}", flush=True)
    print(
        f"[E1v3] {label} — starting at {datetime.now(timezone.utc).isoformat()}",
        flush=True,
    )
    print(f"[E1v3] cmd: {' '.join(cmd)}", flush=True)
    print(f"{'=' * 70}", flush=True)

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=_ROOT)
    wall = time.time() - t0

    rc = proc.returncode
    if rc != 0:
        print(f"[E1v3][ERROR] {label} returncode={rc}", file=sys.stderr, flush=True)

    mrr: float | None = None
    r10: float | None = None
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text())
            mrr = data.get("overall_mrr")
            r10 = data.get("overall_recall10")
        except Exception as e:
            print(
                f"[E1v3][WARN] {label} could not parse {out_path}: {e}",
                file=sys.stderr,
                flush=True,
            )

    print(
        f"[E1v3] {label} done — rc={rc} wall={wall:.1f}s mrr={mrr} r10={r10}",
        flush=True,
    )
    return {
        "row": label,
        "mrr": mrr,
        "r10": r10,
        "wall_seconds": wall,
        "returncode": rc,
    }


def _write_summary(rows: list[dict]) -> None:
    # Find baseline.
    baseline_mrr: float | None = None
    baseline_r10: float | None = None
    for r in rows:
        if r["row"] == "BASELINE":
            baseline_mrr = r["mrr"]
            baseline_r10 = r["r10"]
            break

    summary_path = _OUT_DIR / "summary.csv"
    with summary_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "row",
                "mrr",
                "r10",
                "wall_seconds",
                "returncode",
                "delta_mrr",
                "delta_r10",
            ]
        )
        for r in rows:
            d_mrr = ""
            d_r10 = ""
            if r["row"] != "BASELINE":
                if baseline_mrr is not None and r["mrr"] is not None:
                    # Convention: positive delta means ablation HURTS the score
                    # (baseline - mech > 0 ⇒ disabling the mechanism dropped
                    # the metric ⇒ mechanism contributes positively).
                    d_mrr = f"{baseline_mrr - r['mrr']:.4f}"
                if baseline_r10 is not None and r["r10"] is not None:
                    d_r10 = f"{baseline_r10 - r['r10']:.4f}"
            w.writerow(
                [
                    r["row"],
                    "" if r["mrr"] is None else f"{r['mrr']:.4f}",
                    "" if r["r10"] is None else f"{r['r10']:.4f}",
                    f"{r['wall_seconds']:.1f}",
                    r["returncode"],
                    d_mrr,
                    d_r10,
                ]
            )
    print(f"[E1v3] summary → {summary_path}", flush=True)


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    sha = _git_sha()
    dirty = _git_dirty()
    started_at = datetime.now(timezone.utc).isoformat()

    manifest = {
        "code_hash": sha,
        "dirty": dirty,
        "started_at": started_at,
        "n": 500,
        "n_rows": 1 + len(MECHANISMS),
        "variant": "s",
        "with_consolidation": False,
        "mechanisms": MECHANISMS,
        "rows": [],
    }
    manifest_path = _OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    if dirty:
        print(
            "[E1v3][FATAL] tree is dirty; refusing to launch.",
            file=sys.stderr,
            flush=True,
        )
        return 2

    rows: list[dict] = []

    # 1. BASELINE first — also a sanity-check gate.
    rows.append(_run_row("BASELINE", None))

    if rows[0]["returncode"] != 0 or rows[0]["mrr"] is None:
        print(
            "[E1v3][FATAL] BASELINE failed; aborting before mechanism rows.",
            file=sys.stderr,
            flush=True,
        )
        manifest["rows"] = rows
        manifest["aborted"] = "baseline_failed"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        _write_summary(rows)
        return 1

    # 2. Each mechanism row.
    for mech in MECHANISMS:
        rows.append(_run_row(mech, mech))
        # Persist progress after each row so a crash mid-run still leaves
        # actionable state.
        manifest["rows"] = rows
        manifest["last_completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        _write_summary(rows)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["rows"] = rows
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    _write_summary(rows)

    nonzero = [r for r in rows if r["returncode"] != 0]
    print(f"\n[E1v3] complete. nonzero rows: {len(nonzero)}", flush=True)
    return 0 if not nonzero else 1


if __name__ == "__main__":
    sys.exit(main())
