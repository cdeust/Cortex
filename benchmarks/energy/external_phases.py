"""Attribute sampled power to the phases a benchmark run wrote itself.

The embedding harness times synthetic phases it runs. A retrieval benchmark
(LongMemEval, LoCoMo, BEAM) instead writes its own phase timeline beside its
result (``<stem>.phases.jsonl``, see ``benchmarks/lib/query_log.py``): one
``ingest`` phase per haystack and one ``recall`` phase per scored query, in
the Unix wall clock the ``powermetrics`` sample timestamps use. This module
turns that timeline plus the raw samples into two boundaries:

- **whole leg**: mean power from the first phase start to the last phase end,
  times that duration, divided by the scored queries. It includes ingestion,
  embedding and PostgreSQL work, so it is an upper bound per query.
- **per condition**: mean power of the samples whose end timestamp falls
  inside a phase of that condition, times the summed phase durations. A
  condition whose phases are shorter than the sample interval may catch no
  sample; it is then reported as unmeasured, never estimated.

Carbon follows the SCI arithmetic already used by ``measurement.py``:
``O = E / 3600000 * I`` plus ``M = embodied_rate * elapsed``.

source: Cortex benchmark refresh plan, step 1 (2026-09-30), item (e);
Green Software Foundation SCI specification (see README.md).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from benchmarks.energy.measurement import JOULES_PER_KWH

RECALL = "recall"


@dataclass(frozen=True)
class Window:
    """One timed phase from the benchmark's own timeline."""

    phase: str
    unit: str
    wall_start: float
    wall_end: float

    @property
    def elapsed_s(self) -> float:
        return self.wall_end - self.wall_start


def load_windows(path: Path) -> list[Window]:
    """Read ``<stem>.phases.jsonl``; refuse an empty or inverted timeline."""
    windows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        window = Window(
            row["phase"], str(row["unit"]), row["wall_start"], row["wall_end"]
        )
        if window.wall_end < window.wall_start:
            raise ValueError(
                f"phase {window.phase}/{window.unit} ends before it starts"
            )
        windows.append(window)
    if not windows:
        raise ValueError(f"no phases in {path}")
    return windows


def _inside(samples: list[tuple[float, float]], windows: list[Window]) -> list[float]:
    return [
        watts
        for stamp, watts in samples
        if any(w.wall_start <= stamp <= w.wall_end for w in windows)
    ]


def carbon_g(
    energy_j: float, elapsed_s: float, intensity: float, embodied_rate: float
) -> float:
    """SCI operational plus allocated embodied emissions, in gCO2eq."""
    return energy_j / JOULES_PER_KWH * intensity + embodied_rate * elapsed_s


def idle_power(samples: list[tuple[float, float]], idle: Window) -> float:
    """Mean power of the idle window; refuse an idle window with no sample."""
    values = _inside(samples, [idle])
    if not values:
        raise RuntimeError("no power samples in the idle window; lengthen it")
    return statistics.fmean(values)


def condition_summary(
    samples: list[tuple[float, float]], windows: list[Window], phase: str
) -> dict[str, object]:
    """Energy of one condition, or an explicit unmeasured marker."""
    selected = [w for w in windows if w.phase == phase]
    elapsed = sum(w.elapsed_s for w in selected)
    values = _inside(samples, selected)
    if not values:
        return {
            "units": len(selected),
            "elapsed_s": elapsed,
            "samples": 0,
            "energy_j": None,
            "unmeasured_reason": "no sample end time fell inside these phases",
        }
    energy = statistics.fmean(values) * elapsed
    return {
        "units": len(selected),
        "elapsed_s": elapsed,
        "samples": len(values),
        "mean_system_power_w": statistics.fmean(values),
        "energy_j": energy,
        "energy_j_per_unit": energy / len(selected),
    }


def leg_summary(
    samples: list[tuple[float, float]], windows: list[Window]
) -> dict[str, float]:
    """Whole-leg energy per scored query: an upper bound (see module doc)."""
    span = Window(
        "leg",
        "all",
        min(w.wall_start for w in windows),
        max(w.wall_end for w in windows),
    )
    values = _inside(samples, [span])
    queries = sum(1 for w in windows if w.phase == RECALL)
    if not values or queries == 0:
        raise RuntimeError("leg has no power sample or no scored query")
    energy = statistics.fmean(values) * span.elapsed_s
    return {
        "elapsed_s": span.elapsed_s,
        "samples": len(values),
        "mean_system_power_w": statistics.fmean(values),
        "energy_j": energy,
        "scored_queries": queries,
        "energy_j_per_query_upper_bound": energy / queries,
    }


def summarize(
    samples: list[tuple[float, float]],
    windows: list[Window],
    idle: Window,
    carbon_inputs: tuple[float, float],
) -> dict[str, object]:
    """Both boundaries, the idle reference and per-query carbon."""
    intensity, embodied_rate = carbon_inputs
    leg = leg_summary(samples, windows)
    leg_carbon = carbon_g(leg["energy_j"], leg["elapsed_s"], intensity, embodied_rate)
    return {
        "idle_mean_system_power_w": idle_power(samples, idle),
        "leg": {
            **leg,
            "carbon_gco2eq": leg_carbon,
            "carbon_gco2eq_per_query_upper_bound": leg_carbon / leg["scored_queries"],
        },
        "conditions": {
            phase: condition_summary(samples, windows, phase)
            for phase in sorted({w.phase for w in windows})
        },
    }
