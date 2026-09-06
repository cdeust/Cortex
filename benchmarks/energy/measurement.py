"""Power samples, explicit carbon arithmetic, and reproducible report artifacts.

The SCI equation is used only for the disclosed CPU+GPU+ANE boundary, which is
not a complete device/application SCI assessment. See README.md for sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import subprocess
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np

from benchmarks.energy.workload import Phase


REPO = Path(__file__).resolve().parent.parent.parent
# source: W0-2 functional unit in tasks/codex-green-remediation-plan.md.
TOKENS_PER_UNIT = 1000
# source: NIST SP 811 ch. 4 (W = J/s, kilo = 10^3), ch. 5 (h = 3600 s).
JOULES_PER_KWH = 3_600_000
# source: NIST SP 811 ch. 4, milli = 10^-3.
MILLIWATTS_PER_WATT = 1000
COMBINED_POWER_RE = re.compile(
    r"Combined Power \(CPU \+ GPU \+ ANE\):\s*([0-9.]+)\s*mW"
)
SAMPLE_RE = re.compile(
    r"\*\*\* Sampled system activity \(([^)]+)\).*?\*\*\*\n"
    r"(.*?)(?=\n\*\*\* Sampled system activity|\Z)",
    re.DOTALL,
)


@dataclass
class MeasuredPhase:
    phase: Phase
    samples: int
    mean_system_power_w: float
    idle_power_w: float

    @property
    def raw_system_energy_j(self) -> float:
        # source: NIST SP 811 ch. 4, W = J/s; sampled mean power approximation.
        return self.mean_system_power_w * self.phase.elapsed_s

    @property
    def dynamic_energy_j(self) -> float:
        # Keep negative differences visible; they indicate idle/noise sensitivity.
        return (self.mean_system_power_w - self.idle_power_w) * self.phase.elapsed_s


def parse_power_samples(
    text: str, phase_end: float | None = None
) -> list[tuple[float, float]]:
    samples = []
    blocks = SAMPLE_RE.findall(text)
    for index, (timestamp, body) in enumerate(blocks):
        sampled_at = parsedate_to_datetime(timestamp).timestamp()
        match = COMBINED_POWER_RE.search(body)
        if (
            match is None
            and index == len(blocks) - 1
            and phase_end is not None
            and sampled_at > phase_end
        ):
            warnings.warn(
                "Incomplete final power sample outside measured phases ignored; "
                "raw snapshot preserved",
                RuntimeWarning,
                stacklevel=2,
            )
            continue
        if match is None:
            raise ValueError("sample lacks Combined Power (CPU + GPU + ANE)")
        watts = float(match.group(1)) / MILLIWATTS_PER_WATT
        if not math.isfinite(watts):
            raise ValueError("non-finite power sample")
        samples.append((sampled_at, watts))
    if not samples:
        raise ValueError("no combined CPU+GPU+ANE power samples")
    return samples


def _mean_power(phase: Phase, samples: list[tuple[float, float]]) -> tuple[int, float]:
    values = [
        watts
        for timestamp, watts in samples
        if phase.wall_start <= timestamp <= phase.wall_end
    ]
    if not values:
        raise RuntimeError(f"no power samples in phase {phase.condition}")
    return len(values), statistics.fmean(values)


def apply_power_samples(
    phases: list[Phase], samples: list[tuple[float, float]]
) -> list[MeasuredPhase]:
    power = [_mean_power(phase, samples) for phase in phases]
    idle_by_rep = {
        phase.repetition: mean
        for phase, (_, mean) in zip(phases, power, strict=True)
        if phase.condition == "idle"
    }
    return [
        MeasuredPhase(phase, count, mean, idle_by_rep[phase.repetition])
        for phase, (count, mean) in zip(phases, power, strict=True)
        if phase.condition != "idle"
    ]


def carbon_per_1k_tokens(
    energy_j: float, tokens: int, intensity: float, embodied_g: float
) -> float:
    if tokens <= 0:
        raise ValueError("token count must be positive")
    if any(not math.isfinite(x) or x < 0 for x in (energy_j, intensity, embodied_g)):
        raise ValueError("energy and carbon inputs must be finite and nonnegative")
    # source: https://sci.greensoftware.foundation/ : O = E*I, SCI = (O+M)/R.
    operational_g = energy_j / JOULES_PER_KWH * intensity
    return (operational_g + embodied_g) * TOKENS_PER_UNIT / tokens


def summarize(
    rows: list[MeasuredPhase], mode: str, args: argparse.Namespace
) -> dict[str, float]:
    selected = [row for row in rows if row.phase.condition == mode]
    per_text = [row.raw_system_energy_j / row.phase.operations for row in selected]
    per_tokens = [
        row.raw_system_energy_j * TOKENS_PER_UNIT / row.phase.tokens for row in selected
    ]
    carbon = [
        carbon_per_1k_tokens(
            row.raw_system_energy_j,
            row.phase.tokens,
            args.carbon_intensity,
            args.embodied * row.phase.elapsed_s,
        )
        for row in selected
    ]
    return {
        "repetitions": len(selected),
        "operations_total": sum(row.phase.operations for row in selected),
        "tokens_total": sum(row.phase.tokens for row in selected),
        "energy_j_per_text_mean": statistics.fmean(per_text),
        "energy_j_per_text_stdev": statistics.stdev(per_text),
        "energy_j_per_1k_tokens_mean": statistics.fmean(per_tokens),
        "carbon_gco2eq_per_1k_tokens_mean": statistics.fmean(carbon),
        "idle_subtracted_j_per_text_mean": statistics.fmean(
            row.dynamic_energy_j / row.phase.operations for row in selected
        ),
        "texts_per_second_mean": statistics.fmean(
            row.phase.operations / row.phase.elapsed_s for row in selected
        ),
    }


def _report_row(row: MeasuredPhase, args: argparse.Namespace) -> dict[str, object]:
    return {
        **asdict(row.phase),
        "samples": row.samples,
        "mean_system_power_w": row.mean_system_power_w,
        "idle_power_w": row.idle_power_w,
        "raw_system_energy_j": row.raw_system_energy_j,
        "dynamic_energy_j": row.dynamic_energy_j,
        "embodied_gco2eq": args.embodied * row.phase.elapsed_s,
        "carbon_gco2eq_per_1k_tokens": carbon_per_1k_tokens(
            row.raw_system_energy_j,
            row.phase.tokens,
            args.carbon_intensity,
            args.embodied * row.phase.elapsed_s,
        ),
    }


def _manifest() -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(__file__).parent.iterdir())
            if path.is_file()
        },
        "host": subprocess.check_output(["uname", "-a"], text=True).strip(),
        "raw_measurement": "powermetrics.txt",
        "limitations": [
            "System CPU+GPU+ANE estimates, not process-isolated or device-total energy",
            "Excludes memory, storage, display, supply losses, model load and counting",
            "Mean power uses sample end timestamps within each phase; boundary error",
            "Operator-supplied I and allocated embodied rate are not verified here",
            "Float32 tolerance validates this probe only, not all inputs/devices",
        ],
    }


def write_report(
    args: argparse.Namespace,
    results: tuple[list[MeasuredPhase], dict[str, dict[str, float]]],
    evidence: tuple[bytes, float],
) -> dict[str, object]:
    rows, summary = results
    raw_power, delta = evidence
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_dir = REPO / "benchmarks" / "results" / "energy" / stamp
    out_dir.mkdir(parents=True, exist_ok=False)
    result = {
        "functional_units": ["one embedded text", "1000 model input tokens"],
        "token_definition": (
            "attention_mask sum after truncation; special tokens included"
        ),
        "boundary": "CPU+GPU+ANE power during local inference phases",
        "duration_seconds": args.duration_seconds,
        "repetitions": args.repetitions,
        "batch_size": args.batch_size,
        "sample_rate_ms": args.sample_rate_ms,
        "carbon_intensity_gco2eq_per_kwh": args.carbon_intensity,
        "embodied_rate_gco2eq_per_second": args.embodied,
        "carbon_formula": (
            "((energy_j / 3600000) * I + embodied_rate * elapsed_s) * 1000 / tokens"
        ),
        "max_abs_output_delta_scalar_vs_batch": delta,
        "equivalence_atol": float(np.finfo(np.float32).eps),
        "equivalence_rtol": 0,
        "rows": [_report_row(row, args) for row in rows],
        "summary": summary,
    }
    (out_dir / "powermetrics.txt").write_bytes(raw_power)
    for name, payload in (("results.json", result), ("MANIFEST.json", _manifest())):
        (out_dir / name).write_text(
            json.dumps(payload, indent=2, allow_nan=False) + "\n"
        )
    return {"result_dir": str(out_dir), "summary": summary}
