"""E1 v3 — LoCoMo per-mechanism ablation runner (two-baseline design).

Drives `benchmarks/locomo/run_benchmark.py` once per row, serially, against
the same PG instance. Each row writes its result JSON via `--results-out`.
After all rows complete, an aggregate `summary.csv` and `manifest.json`
are written.

Output: benchmarks/results/ablation/locomo_v3/

Why serial: the harness mutates a shared PG database (db.clear() per
conversation). Parallel rows would contaminate each other's haystacks.

Two-baseline design (per tasks/e1-v3-locomo-smoke-finding.md, Option B):

LoCoMo session timestamps are real 2023 conversation dates. At 2026 wall
time, every loaded memory is ≈3 years old. Cortex's compression gates
(COMPRESSION_GIST_AGE_HOURS=168, COMPRESSION_TAG_AGE_HOURS=720) fire on
absolute timestamp diff, so consolidation collapses the corpus to gists/
tags on first pass. Smoke: MRR 0.866 (no consolidation) → 0.222 (with).

To preserve honest per-mechanism evidence:

- Longitudinal read-path mechanisms (RECONSOLIDATION, CO_ACTIVATION,
  ADAPTIVE_DECAY) are ablated against BASELINE_NO_CONSOLIDATION. These do
  not require a consolidation pass — their effect is heat / access / co-
  access tracking that accumulates via cross-question reads.

- Consolidation-only mechanisms (CASCADE, INTERFERENCE,
  HOMEOSTATIC_PLASTICITY, SYNAPTIC_PLASTICITY, MICROGLIAL_PRUNING,
  TWO_STAGE_MODEL, EMOTIONAL_DECAY, TRIPARTITE_SYNAPSE, SCHEMA_ENGINE) are
  ablated against BASELINE_WITH_CONSOLIDATION. Each row's delta is the
  mechanism's role within the observed (timestamp-collision) regime;
  this is documented as a benchmark-property disclosure in the writeup.

14 rows total. Estimated wall ~7h.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OUT_DIR = _ROOT / "benchmarks" / "results" / "ablation" / "locomo_v3"
_HARNESS = _ROOT / "benchmarks" / "locomo" / "run_benchmark.py"


@dataclass
class Row:
    label: str
    ablate: str | None
    with_consolidation: bool
    anchor: str  # the BASELINE label this row's delta is computed against


# Two-baseline 14-row design.
ROWS: list[Row] = [
    # === Baseline 1: NO consolidation, anchor for longitudinal read-path mechs ===
    Row("BASELINE_NO_CONSOLIDATION", ablate=None,
        with_consolidation=False, anchor="BASELINE_NO_CONSOLIDATION"),

    # Longitudinal read-path — ablated vs NO_CONSOLIDATION
    Row("RECONSOLIDATION", ablate="RECONSOLIDATION",
        with_consolidation=False, anchor="BASELINE_NO_CONSOLIDATION"),
    Row("CO_ACTIVATION", ablate="CO_ACTIVATION",
        with_consolidation=False, anchor="BASELINE_NO_CONSOLIDATION"),
    Row("ADAPTIVE_DECAY", ablate="ADAPTIVE_DECAY",
        with_consolidation=False, anchor="BASELINE_NO_CONSOLIDATION"),

    # === Baseline 2: WITH consolidation, anchor for consolidation-only mechs ===
    Row("BASELINE_WITH_CONSOLIDATION", ablate=None,
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),

    # Consolidation-only — ablated vs WITH_CONSOLIDATION
    Row("CASCADE", ablate="CASCADE",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("INTERFERENCE", ablate="INTERFERENCE",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("HOMEOSTATIC_PLASTICITY", ablate="HOMEOSTATIC_PLASTICITY",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("SYNAPTIC_PLASTICITY", ablate="SYNAPTIC_PLASTICITY",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("MICROGLIAL_PRUNING", ablate="MICROGLIAL_PRUNING",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("TWO_STAGE_MODEL", ablate="TWO_STAGE_MODEL",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("EMOTIONAL_DECAY", ablate="EMOTIONAL_DECAY",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("TRIPARTITE_SYNAPSE", ablate="TRIPARTITE_SYNAPSE",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
    Row("SCHEMA_ENGINE", ablate="SCHEMA_ENGINE",
        with_consolidation=True, anchor="BASELINE_WITH_CONSOLIDATION"),
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


def _run_row(row: Row) -> dict:
    out_path = _OUT_DIR / f"{row.label}.json"
    cmd = [
        "uv", "run", "python", str(_HARNESS),
        "--results-out", str(out_path),
    ]
    if row.with_consolidation:
        cmd.append("--with-consolidation")
    if row.ablate is not None:
        cmd += ["--ablate", row.ablate]

    print(f"\n{'=' * 70}", flush=True)
    print(f"[E1v3-LoCoMo] {row.label} — start {datetime.now(timezone.utc).isoformat()}",
          flush=True)
    print(f"[E1v3-LoCoMo] cmd: {' '.join(cmd)}", flush=True)
    print(f"{'=' * 70}", flush=True)

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=_ROOT)
    wall = time.time() - t0

    rc = proc.returncode
    if rc != 0:
        print(f"[E1v3-LoCoMo][ERROR] {row.label} returncode={rc}",
              file=sys.stderr, flush=True)

    mrr: float | None = None
    r10: float | None = None
    cat_mrr: dict[str, float] = {}
    cat_r10: dict[str, float] = {}
    if out_path.exists():
        try:
            data = json.loads(out_path.read_text())
            mrr = data.get("overall_mrr")
            r10 = data.get("overall_recall10")
            cat_mrr = data.get("category_mrr", {}) or {}
            cat_r10 = data.get("category_recall10", {}) or {}
        except Exception as e:
            print(f"[E1v3-LoCoMo][WARN] {row.label} parse {out_path}: {e}",
                  file=sys.stderr, flush=True)

    print(f"[E1v3-LoCoMo] {row.label} done — rc={rc} wall={wall:.1f}s "
          f"mrr={mrr} r10={r10}", flush=True)
    return {
        "row": row.label,
        "anchor": row.anchor,
        "with_consolidation": row.with_consolidation,
        "ablate": row.ablate,
        "mrr": mrr,
        "r10": r10,
        "category_mrr": cat_mrr,
        "category_recall10": cat_r10,
        "wall_seconds": wall,
        "returncode": rc,
    }


def _write_summary(rows: list[dict]) -> None:
    # Build anchor → (mrr, r10) map.
    anchors: dict[str, tuple[float | None, float | None]] = {}
    for r in rows:
        if r["row"] == r["anchor"]:
            anchors[r["row"]] = (r["mrr"], r["r10"])

    summary_path = _OUT_DIR / "summary.csv"
    with summary_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "row", "anchor", "with_consolidation", "ablate",
            "mrr", "r10", "wall_seconds", "returncode",
            "delta_mrr_vs_anchor", "delta_r10_vs_anchor",
        ])
        for r in rows:
            d_mrr = ""
            d_r10 = ""
            if r["row"] != r["anchor"]:
                a_mrr, a_r10 = anchors.get(r["anchor"], (None, None))
                if a_mrr is not None and r["mrr"] is not None:
                    # positive delta = ablation hurt the metric
                    d_mrr = f"{a_mrr - r['mrr']:.4f}"
                if a_r10 is not None and r["r10"] is not None:
                    d_r10 = f"{a_r10 - r['r10']:.4f}"
            w.writerow([
                r["row"], r["anchor"], r["with_consolidation"],
                r["ablate"] or "",
                "" if r["mrr"] is None else f"{r['mrr']:.4f}",
                "" if r["r10"] is None else f"{r['r10']:.4f}",
                f"{r['wall_seconds']:.1f}",
                r["returncode"], d_mrr, d_r10,
            ])
    print(f"[E1v3-LoCoMo] summary → {summary_path}", flush=True)


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    sha = _git_sha()
    dirty = _git_dirty()
    started_at = datetime.now(timezone.utc).isoformat()

    manifest = {
        "code_hash": sha,
        "dirty": dirty,
        "started_at": started_at,
        "n_rows": len(ROWS),
        "design": "two-baseline",
        "rows_spec": [
            {
                "label": r.label,
                "ablate": r.ablate,
                "with_consolidation": r.with_consolidation,
                "anchor": r.anchor,
            }
            for r in ROWS
        ],
        "rows": [],
    }
    manifest_path = _OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    if dirty:
        print("[E1v3-LoCoMo][FATAL] tree is dirty; refusing to launch.",
              file=sys.stderr, flush=True)
        return 2

    rows: list[dict] = []

    # 1. BASELINE_NO_CONSOLIDATION first — sanity gate vs CLAUDE.md (~0.794 MRR).
    rows.append(_run_row(ROWS[0]))
    if rows[0]["returncode"] != 0 or rows[0]["mrr"] is None:
        print("[E1v3-LoCoMo][FATAL] BASELINE_NO_CONSOLIDATION failed; aborting.",
              file=sys.stderr, flush=True)
        manifest["rows"] = rows
        manifest["aborted"] = "baseline_no_consolidation_failed"
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        _write_summary(rows)
        return 1

    # CLAUDE.md sanity tolerance: ±0.05 around 0.794. Soft warning if outside.
    bn_mrr = rows[0]["mrr"]
    if abs(bn_mrr - 0.794) > 0.05:
        print(
            f"[E1v3-LoCoMo][WARN] BASELINE_NO_CONSOLIDATION MRR={bn_mrr:.3f} "
            f"deviates >0.05 from CLAUDE.md headline 0.794. Continuing — "
            f"document in writeup.",
            file=sys.stderr, flush=True,
        )

    # 2. Remaining 13 rows.
    for row in ROWS[1:]:
        rows.append(_run_row(row))
        manifest["rows"] = rows
        manifest["last_completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
        _write_summary(rows)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["rows"] = rows
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    _write_summary(rows)

    nonzero = [r for r in rows if r["returncode"] != 0]
    print(f"\n[E1v3-LoCoMo] complete. nonzero rows: {len(nonzero)}", flush=True)
    return 0 if not nonzero else 1


if __name__ == "__main__":
    sys.exit(main())
