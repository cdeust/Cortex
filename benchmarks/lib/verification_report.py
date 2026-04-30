"""Master verification-report aggregator.

Reads JSON results from all 6 verification experiments and emits a single
Markdown report — the artifact that updates the paper's Limitations section.

Sources:
    E1 ablation       → benchmarks/results/ablation/<run>/result.json
    E2 N-scan         → benchmarks/results/n_scan/<run>/result.json
    E3 decay sweep    → benchmarks/results/decay_sweep/<run>/result.json
    E4 longitudinal   → benchmarks/results/longitudinal/<run>/result.json
    E5 cross-benchmark → benchmarks/results/cross_benchmark/<run>/{calibration,evaluation,reference}.json
    E6 telemetry      → ~/.claude/methodology/telemetry.jsonl

Critical contract:
    - Numbers come straight from the JSON files. The aggregator does NO
      computation other than rounding for display + 95% CIs from per-question
      raw data when present.
    - Missing experiments render as `// TODO: not yet run`. They are NEVER
      filled with placeholders.

CLI:
    python -m benchmarks.lib.verification_report
        [--out docs/papers/verification-results.md]
        [--results-dir benchmarks/results]
        [--telemetry ~/.claude/methodology/telemetry.jsonl]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Pre-registered hypotheses + thresholds (locked at protocol-write time).
# Source: tasks/verification-protocol.md §1-6.
HYPOTHESES: dict[str, dict[str, Any]] = {
    "E1": {
        "name": "Ablation — each claimed component contributes",
        "claim": "Removing any single load-bearing module reduces overall MRR by ≥0.01.",
        "threshold": "every ablated module shows ΔMRR ≥ +0.01 vs baseline",
        "pass_op": ">=",
        "pass_value": 0.01,
    },
    "E2": {
        "name": "N-scan — retrieval scales with corpus size",
        "claim": "MRR does not collapse (>20% relative drop) as N grows from 100K to 1M.",
        "threshold": "MRR(1M) ≥ 0.80 × MRR(100K)",
        "pass_op": ">=",
        "pass_value": 0.80,
    },
    "E3": {
        "name": "Decay sweep — heat decay is not the dominant signal",
        "claim": "Sweeping decay λ from 0.85 to 0.999 changes overall MRR by <0.05 absolute.",
        "threshold": "MRR_max - MRR_min < 0.05 across the sweep",
        "pass_op": "<",
        "pass_value": 0.05,
    },
    "E4": {
        "name": "Longitudinal — no drift over a 30-day window",
        "claim": "Repeated calibration over 30 simulated days holds MRR within ±0.02 of day-1.",
        "threshold": "|MRR(day=k) - MRR(day=1)| < 0.02 for all k",
        "pass_op": "<",
        "pass_value": 0.02,
    },
    "E5": {
        "name": "Cross-benchmark — config calibrated on LongMemEval transfers to LoCoMo",
        "claim": "Phase-B (LongMemEval-tuned, AS-IS to LoCoMo) MRR ≥ 0.92 × Phase-C ceiling.",
        "threshold": "Phase-B MRR / Phase-C MRR ≥ 0.92",
        "pass_op": ">=",
        "pass_value": 0.92,
    },
    "E6": {
        "name": "Telemetry — production p95 latency stays bounded",
        "claim": "p95 recall latency over the last 1000 sessions is <200ms.",
        "threshold": "p95(recall_ms) < 200",
        "pass_op": "<",
        "pass_value": 200.0,
    },
}


@dataclass
class ExpResult:
    exp_id: str
    found: bool = False
    observed: float | None = None
    raw_path: str | None = None
    detail_md: str = ""
    ci95: tuple[float, float] | None = None

    @property
    def name(self) -> str:
        return HYPOTHESES[self.exp_id]["name"]

    @property
    def threshold(self) -> str:
        return HYPOTHESES[self.exp_id]["threshold"]

    @property
    def verdict(self) -> str:
        if not self.found or self.observed is None:
            return "INCONCLUSIVE"
        h = HYPOTHESES[self.exp_id]
        op, val = h["pass_op"], h["pass_value"]
        cmp = {
            ">=": self.observed >= val,
            "<": self.observed < val,
            ">": self.observed > val,
            "<=": self.observed <= val,
        }
        return "PASS" if cmp.get(op, False) else "FAIL"


def _bootstrap_ci(
    values: list[float], n_resamples: int = 1000
) -> tuple[float, float] | None:
    """Percentile bootstrap 95% CI for the mean. None if <10 values."""
    if not values or len(values) < 10:
        return None
    import random

    rng = random.Random(42)
    n = len(values)
    means = [
        sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_resamples)
    ]
    means.sort()
    return (means[int(0.025 * n_resamples)], means[int(0.975 * n_resamples)])


def _latest_run(dir_path: Path) -> Path | None:
    if not dir_path.exists():
        return None
    runs = sorted([p for p in dir_path.iterdir() if p.is_dir()])
    return runs[-1] if runs else None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _read_e1(results_dir: Path) -> ExpResult:
    """Ablation: every claimed component must contribute ΔMRR ≥ 0.01."""
    out = ExpResult(exp_id="E1")
    run = _latest_run(results_dir / "ablation")
    payload = _load_json(run / "result.json") if run else None
    if not payload:
        return out
    rows = payload.get("rows") or payload.get("ablations") or []
    deltas = [r.get("delta_mrr") for r in rows if r.get("delta_mrr") is not None]
    if not deltas:
        return out
    out.found = True
    out.raw_path = str(run / "result.json")
    out.observed = min(deltas)  # tightest constraint — the worst component
    out.detail_md = "| Component | ΔMRR |\n|---|---|\n" + "\n".join(
        f"| {r.get('component', '?')} | {r.get('delta_mrr', 0):+.3f} |" for r in rows
    )
    return out


def _read_simple(
    exp_id: str, results_dir: Path, subdir: str, metric_key: str
) -> ExpResult:
    """Generic reader for E2/E3/E4 — single scalar at result.json[metric_key]."""
    out = ExpResult(exp_id=exp_id)
    run = _latest_run(results_dir / subdir)
    payload = _load_json(run / "result.json") if run else None
    if not payload or payload.get(metric_key) is None:
        return out
    out.found = True
    out.raw_path = str(run / "result.json")
    out.observed = float(payload[metric_key])
    if isinstance(payload.get("raw_per_question"), list):
        out.ci95 = _bootstrap_ci(payload["raw_per_question"])
    head = payload.get("rows", [])[:8]
    if head and isinstance(head[0], dict):
        keys = list(head[0].keys())[:4]
        out.detail_md = (
            "| " + " | ".join(keys) + " |\n"
            "|"
            + "|".join(["---"] * len(keys))
            + "|\n"
            + "\n".join(
                "| " + " | ".join(str(r.get(k, "")) for k in keys) + " |" for r in head
            )
        )
    return out


def _read_e5(results_dir: Path) -> ExpResult:
    """Cross-benchmark: ratio = Phase-B MRR / Phase-C MRR."""
    out = ExpResult(exp_id="E5")
    run = _latest_run(results_dir / "cross_benchmark")
    if not run:
        return out
    eval_p = _load_json(run / "evaluation.json")
    ref_p = _load_json(run / "reference.json")
    if not eval_p or not ref_p:
        return out
    b = (eval_p.get("result") or {}).get("mrr")
    c = (ref_p.get("best") or {}).get("mrr")
    if b is None or c is None or c == 0:
        return out
    out.found = True
    out.raw_path = str(run)
    out.observed = b / c
    out.detail_md = (
        f"- Phase A winner cell: `{eval_p.get('winner_cell')}`\n"
        f"- Phase B MRR (no retune on LoCoMo): {b:.3f}\n"
        f"- Phase C best MRR (LoCoMo-tuned): {c:.3f}\n"
        f"- Ratio B/C: {b / c:.3f}"
    )
    summary = run / "summary.md"
    if summary.exists():
        out.detail_md += (
            "\n\n<details><summary>Phase summary</summary>\n\n"
            + summary.read_text()
            + "\n</details>"
        )
    return out


def _read_e6(telemetry_path: Path) -> ExpResult:
    """Telemetry: p95 recall latency over recent sessions."""
    out = ExpResult(exp_id="E6")
    if not telemetry_path.exists():
        return out
    latencies: list[float] = []
    try:
        with telemetry_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                v = rec.get("recall_ms")
                if isinstance(v, (int, float)):
                    latencies.append(float(v))
    except OSError:
        return out
    if len(latencies) < 100:
        return out
    latencies.sort()
    p95 = latencies[
        max(0, min(len(latencies) - 1, math.ceil(0.95 * len(latencies)) - 1))
    ]
    p99 = latencies[max(0, math.ceil(0.99 * len(latencies)) - 1)]
    out.found = True
    out.raw_path = str(telemetry_path)
    out.observed = p95
    out.detail_md = (
        f"- Samples: {len(latencies)}\n"
        f"- p50: {latencies[len(latencies) // 2]:.1f}ms\n"
        f"- p95: {p95:.1f}ms\n"
        f"- p99: {p99:.1f}ms"
    )
    return out


def _render_section(r: ExpResult) -> str:
    h = HYPOTHESES[r.exp_id]
    if not r.found:
        return (
            f"## {r.exp_id} — {r.name}\n\n"
            f"- **Hypothesis:** {h['claim']}\n"
            f"- **Threshold:** {r.threshold}\n"
            f"- **Result:** `// TODO: not yet run`\n"
        )
    obs_str = f"{r.observed:.4f}" if r.observed is not None else "N/A"
    ci_str = f"\n- **95% CI:** [{r.ci95[0]:.4f}, {r.ci95[1]:.4f}]" if r.ci95 else ""
    parts = [
        f"## {r.exp_id} — {r.name}",
        "",
        f"- **Hypothesis:** {h['claim']}",
        f"- **Threshold:** {r.threshold}",
        f"- **Observed:** {obs_str}{ci_str}",
        f"- **Verdict:** **{r.verdict}**",
        f"- **Source:** `{r.raw_path}`",
    ]
    if r.detail_md:
        parts += ["", "### Detail", "", r.detail_md]
    return "\n".join(parts) + "\n"


def _render_summary(results: list[ExpResult]) -> str:
    lines = [
        "| Exp | Claim | Threshold | Observed | Verdict |",
        "|-----|-------|-----------|----------|---------|",
    ]
    for r in results:
        h = HYPOTHESES[r.exp_id]
        claim = h["claim"][:60] + ("…" if len(h["claim"]) > 60 else "")
        if not r.found:
            obs, verdict = "// TODO: not yet run", "—"
        else:
            obs = f"{r.observed:.4f}" if r.observed is not None else "N/A"
            verdict = r.verdict
        lines.append(f"| {r.exp_id} | {claim} | {r.threshold} | {obs} | {verdict} |")
    return "\n".join(lines) + "\n"


def build_report(results_dir: Path, telemetry_path: Path) -> str:
    """Aggregate all 6 experiments and produce the master Markdown report."""
    results = [
        _read_e1(results_dir),
        _read_simple("E2", results_dir, "n_scan", "mrr_ratio_1m_over_100k"),
        _read_simple("E3", results_dir, "decay_sweep", "mrr_range"),
        _read_simple("E4", results_dir, "longitudinal", "max_drift"),
        _read_e5(results_dir),
        _read_e6(telemetry_path),
    ]
    parts = [
        "# Verification results — paper Limitations update",
        "",
        "Auto-generated by `benchmarks/lib/verification_report.py`. Do NOT hand-edit.",
        "",
        "## Summary",
        "",
        _render_summary(results),
        "",
    ]
    for r in results:
        parts += [_render_section(r), ""]
    return "\n".join(parts)


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--out",
        type=str,
        default=str(repo / "docs" / "papers" / "verification-results.md"),
    )
    parser.add_argument(
        "--results-dir", type=str, default=str(repo / "benchmarks" / "results")
    )
    parser.add_argument(
        "--telemetry",
        type=str,
        default=str(Path.home() / ".claude" / "methodology" / "telemetry.jsonl"),
    )
    args = parser.parse_args()

    report = build_report(Path(args.results_dir), Path(args.telemetry))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"Report written to: {out}")
    print(f"  {len(report.splitlines())} lines, {len(report)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
