"""Emergence tracker — system-level metric tracking for neuroscience insights.

Tracks properties that EMERGE from the interaction of individual mechanisms,
not from any single module. These are the phenomena that validate whether
Cortex's neuroscience model produces biologically realistic behavior:

- Spacing effect: spaced repetitions improve retention vs massed practice
- Testing effect: retrieval practice strengthens memory more than re-encoding
- Sleep benefit: consolidation during SWR improves next-day retrieval
- Schema acceleration: schema-consistent memories consolidate faster
- Interference resolution: similar memories eventually separate over time
- Forgetting curve: power-law decay of retrieval probability
- Phase-locking: encoding during theta encoding-phase improves retention

Forgetting curve fitting and aggregate report are in emergence_metrics.py.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ── Metric Events ────────────────────────────────────────────────────────


@dataclass
class MemoryEvent:
    """A single event in a memory's lifecycle for tracking."""

    memory_id: int
    event_type: str  # "encode", "retrieve", "replay", "consolidate", "forget"
    timestamp_hours: float  # Hours since system start
    theta_phase: float = 0.0
    ach_level: float = 0.5
    schema_match: float = 0.0
    consolidation_stage: str = "labile"
    heat: float = 1.0
    success: bool = True


# ── Spacing Effect ───────────────────────────────────────────────────────


def compute_spacing_benefit(
    access_times: list[float],
    current_heat: float,
) -> float:
    """Measure spacing effect: do spaced accesses correlate with higher heat?

    Returns spacing regularity score [0, 1] where:
    - 1.0 = perfectly spaced (equal intervals)
    - 0.0 = maximally massed (all accesses clustered)

    Args:
        access_times: Timestamps (hours) of memory accesses.
        current_heat: Current heat of the memory.

    Returns:
        Spacing regularity score.
    """
    if len(access_times) < 3:
        return 0.5

    intervals = [
        access_times[i + 1] - access_times[i] for i in range(len(access_times) - 1)
    ]
    if not intervals:
        return 0.5

    mean_interval = sum(intervals) / len(intervals)
    if mean_interval < 0.01:
        return 0.0

    variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
    cv = math.sqrt(variance) / mean_interval if mean_interval > 0 else 0.0

    regularity = max(0.0, 1.0 - cv / 2.0)
    return round(regularity, 4)


# ── Testing Effect ───────────────────────────────────────────────────────


def compute_testing_benefit(
    retrieval_count: int,
    re_encode_count: int,
    current_heat: float,
) -> dict[str, float]:
    """Measure testing effect: does retrieval practice preserve heat better?

    Returns metrics comparing retrieval vs re-encoding effectiveness.
    """
    total = retrieval_count + re_encode_count
    if total == 0:
        return {"retrieval_fraction": 0.0, "heat": current_heat, "testing_benefit": 0.0}

    retrieval_fraction = retrieval_count / total
    testing_benefit = retrieval_fraction * current_heat
    return {
        "retrieval_fraction": round(retrieval_fraction, 4),
        "heat": round(current_heat, 4),
        "testing_benefit": round(testing_benefit, 4),
    }


# ── Schema Acceleration ─────────────────────────────────────────────────


def _avg_consolidation_time(mems: list[dict]) -> float:
    """Average hours to reach consolidated stage."""
    times = [
        m.get("hours_in_stage", 0) + 24.0
        for m in mems
        if m.get("consolidation_stage") == "consolidated"
    ]
    return sum(times) / len(times) if times else float("inf")


def _consolidated_fraction(mems: list[dict]) -> float:
    """Fraction of memories that reached consolidated stage."""
    if not mems:
        return 0.0
    return sum(1 for m in mems if m.get("consolidation_stage") == "consolidated") / len(
        mems
    )


def compute_schema_acceleration_metric(
    schema_consistent_memories: list[dict],
    schema_inconsistent_memories: list[dict],
) -> dict[str, float]:
    """Measure schema acceleration: do schema-consistent memories consolidate faster?

    Compares average hours to reach CONSOLIDATED stage.
    """
    consistent_time = _avg_consolidation_time(schema_consistent_memories)
    inconsistent_time = _avg_consolidation_time(schema_inconsistent_memories)

    if inconsistent_time > 0 and consistent_time < float("inf"):
        acceleration_ratio = inconsistent_time / max(consistent_time, 0.1)
    else:
        acceleration_ratio = 1.0

    return {
        "consistent_count": len(schema_consistent_memories),
        "inconsistent_count": len(schema_inconsistent_memories),
        "consistent_consolidated_fraction": round(
            _consolidated_fraction(schema_consistent_memories), 4
        ),
        "inconsistent_consolidated_fraction": round(
            _consolidated_fraction(schema_inconsistent_memories), 4
        ),
        "acceleration_ratio": round(acceleration_ratio, 4),
    }


# ── Phase-Locking ────────────────────────────────────────────────────────


def compute_phase_locking_benefit(
    encoding_phase_memories: list[dict],
    retrieval_phase_memories: list[dict],
) -> dict[str, float]:
    """Measure whether encoding during theta encoding-phase improves retention.

    Compares heat/survival of memories encoded at different theta phases.
    """

    def avg_heat(mems: list[dict]) -> float:
        heats = [m.get("heat", 0) for m in mems]
        return sum(heats) / len(heats) if heats else 0.0

    def survival_rate(mems: list[dict], min_heat: float = 0.1) -> float:
        if not mems:
            return 0.0
        alive = sum(1 for m in mems if m.get("heat", 0) >= min_heat)
        return alive / len(mems)

    enc_heat = avg_heat(encoding_phase_memories)
    ret_heat = avg_heat(retrieval_phase_memories)

    return {
        "encoding_phase_count": len(encoding_phase_memories),
        "retrieval_phase_count": len(retrieval_phase_memories),
        "encoding_phase_avg_heat": round(enc_heat, 4),
        "retrieval_phase_avg_heat": round(ret_heat, 4),
        "phase_benefit": round(enc_heat - ret_heat, 4),
        "encoding_phase_survival": round(survival_rate(encoding_phase_memories), 4),
        "retrieval_phase_survival": round(survival_rate(retrieval_phase_memories), 4),
    }
