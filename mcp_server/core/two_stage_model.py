"""Two-stage memory model — hippocampal-cortical transfer protocol.

Models the McClelland et al. (1995) Complementary Learning Systems theory:
the hippocampus fast-binds episodic memories that are fragile and capacity-
limited, while the cortex slowly integrates semantic knowledge that is stable
and high-capacity. Transfer happens via replay-driven interleaved training.

Hippocampal Store:
  - Fast binding (immediate): one-shot encoding
  - High interference: similar memories compete
  - Capacity-limited: only ~N active traces
  - Context-dependent: directory/domain required for retrieval
  - Decays fast without replay (labile -> lost)

Cortical Store:
  - Slow integration (via SWR replay): many repetitions needed
  - Low interference: interleaved training prevents catastrophic forgetting
  - High capacity: no practical limit
  - Context-free: retrievable from any context
  - Very stable once formed (consolidated)

Transfer protocol:
  1. Memory enters hippocampal store (fast bind, labile stage)
  2. During SWR replay: hippocampal trace activates cortical target
  3. Repeated replay gradually builds cortical representation
  4. Schema-consistent memories transfer faster (schema acceleration)
  5. Once cortical trace is strong: hippocampal version can release

The hippocampal_dependency field in Memory tracks this:
  1.0 = fully hippocampal (just encoded, no cortical trace)
  0.5 = transitional (partial cortical trace, hippocampus still needed)
  0.0 = cortically independent (fully consolidated, hippocampus can release)

Note: hippocampal_dependency is an engineering construct that combines the
qualitative CLS framework (McClelland 1995) with quantitative learning rates
from C-HORSE (Ketz et al., eLife 12:e77185, 2023). The original CLS paper
does not define a scalar "dependency" metric; we model it as the complement
of cortical trace strength, decaying via the cortical learning rate (0.02)
during replay-driven transfer.

This integrates with:
  - cascade.py: consolidation stages track biochemical maturation
  - oscillatory_clock.py: SWR windows gate replay-driven transfer
  - schema_engine.py: schema match accelerates cortical integration
  - interference.py: hippocampal interference drives need for transfer

References:
    McClelland JL, McNaughton BL, O'Reilly RC (1995) Why there are
        complementary learning systems. Psychol Rev 102:419-457
    Kumaran D, Hassabis D, McClelland JL (2016) What learning systems
        do intelligent agents need? Neuron 92:1258-1273
    Frankland PW, Bontempi B (2005) The organization of recent and
        remote memories. Nat Rev Neurosci 6:119-130
    Ketz NA, et al. (2023) C-HORSE: A computational model of hippocampal-
        cortical complementary learning. eLife 12:e77185
    Tse D, et al. (2007) Schemas and memory consolidation. Science 316:76-82

Pure business logic — no I/O.
"""

from __future__ import annotations

import math

from mcp_server.core.two_stage_transfer import (
    compute_interleaving_schedule,
    compute_transfer_delta,
    update_hippocampal_dependency,
)

__all__ = [
    "compute_transfer_delta",
    "update_hippocampal_dependency",
    "classify_memory_store",
    "should_release_hippocampal_trace",
    "compute_hippocampal_pressure",
    "compute_consolidation_priority",
    "select_replay_candidates",
    "compute_interleaving_schedule",
    "compute_transfer_metrics",
]


# ── Configuration ─────────────────────────────────────────────────────────

# Engineering choice. McClelland et al. (1995) discuss hippocampal capacity
# limits as a motivation for CLS but provide no specific number. We use 100
# as a practical bound for active traces in a session-based AI memory system.
_HIPPOCAMPAL_CAPACITY = 100

# Engineering choice: dependency threshold below which a memory is considered
# cortically independent and no longer needs hippocampal support.
_CORTICAL_INDEPENDENCE_THRESHOLD = 0.15

# Engineering choice: threshold below which the hippocampal trace can be freed.
# Calibrated to the cortical learning rate (0.02) from C-HORSE (Ketz et al., 2023).
_HIPPOCAMPAL_RELEASE_THRESHOLD = 0.05


# ── Store Classification ─────────────────────────────────────────────────


def classify_memory_store(
    hippocampal_dependency: float,
    consolidation_stage: str,
) -> str:
    """Classify which store a memory primarily resides in.

    Returns:
        "hippocampal" — primarily hippocampus-dependent
        "transitional" — being transferred (partial cortical trace)
        "cortical" — cortically independent
    """
    if hippocampal_dependency > 0.7:
        return "hippocampal"
    if hippocampal_dependency > _CORTICAL_INDEPENDENCE_THRESHOLD:
        return "transitional"
    return "cortical"


def should_release_hippocampal_trace(
    hippocampal_dependency: float,
    consolidation_stage: str,
    heat: float,
) -> bool:
    """Determine if a memory's hippocampal trace can be released.

    Release criteria:
    - Cortically independent (dependency < threshold)
    - Consolidated stage
    - Not currently hot (not being actively used)
    """
    return (
        hippocampal_dependency <= _HIPPOCAMPAL_RELEASE_THRESHOLD
        and consolidation_stage == "consolidated"
        and heat < 0.3
    )


# ── Capacity Pressure ────────────────────────────────────────────────────


def compute_hippocampal_pressure(
    active_hippocampal_count: int,
    *,
    capacity: int = _HIPPOCAMPAL_CAPACITY,
) -> float:
    """Compute capacity pressure on the hippocampal store.

    As the store fills, pressure increases, signaling that consolidation
    and transfer need to happen faster to free up space.

    Returns pressure [0, 1]. >0.8 = critical, needs immediate consolidation.
    """
    if capacity <= 0:
        return 1.0
    ratio = active_hippocampal_count / capacity
    return 1.0 / (1.0 + math.exp(-8.0 * (ratio - 0.7)))


# ── Consolidation Priority ──────────────────────────────────────────────


def compute_consolidation_priority(
    hippocampal_dependency: float,
    importance: float,
    heat: float,
    schema_match: float,
    hours_since_creation: float,
) -> float:
    """Compute priority for replay-driven consolidation.

    Higher priority = should be replayed sooner.
    Prioritizes: high importance, moderate dependency (in transfer zone),
    schema-consistent (faster transfer), aging (time pressure).
    """
    dep_priority = _dependency_sweet_spot(hippocampal_dependency)
    age_factor = min(hours_since_creation / 168.0, 1.0)
    schema_boost = schema_match * 0.3

    priority = (
        importance * 0.30
        + dep_priority * 0.25
        + age_factor * 0.20
        + schema_boost * 0.15
        + heat * 0.10
    )

    return round(max(0.0, min(1.0, priority)), 4)


def _dependency_sweet_spot(hippocampal_dependency: float) -> float:
    """Transitional memories (0.3-0.7) have highest priority.

    Fully hippocampal haven't started transfer; cortical are done.
    """
    priority = 1.0 - 4.0 * (hippocampal_dependency - 0.5) ** 2
    return max(0.0, priority)


# ── Replay Sequence Selection ────────────────────────────────────────────


def select_replay_candidates(
    memories: list[dict],
    max_candidates: int = 10,
) -> list[dict]:
    """Select memories for SWR replay, ordered by consolidation priority.

    Filters out already-consolidated and labile memories, then scores
    and ranks by consolidation priority.
    """
    candidates = []

    for mem in memories:
        scored = _score_replay_candidate(mem)
        if scored is not None:
            candidates.append(scored)

    candidates.sort(key=lambda x: x["replay_priority"], reverse=True)
    return candidates[:max_candidates]


def _score_replay_candidate(mem: dict) -> dict | None:
    """Score a single memory for replay eligibility and priority.

    Returns the memory dict with 'replay_priority' added, or None if ineligible.
    """
    dep = mem.get("hippocampal_dependency", 1.0)
    if dep <= _HIPPOCAMPAL_RELEASE_THRESHOLD:
        return None

    stage = mem.get("consolidation_stage", "labile")
    if stage == "labile":
        return None

    priority = compute_consolidation_priority(
        dep,
        mem.get("importance", 0.5),
        mem.get("heat", 0.5),
        mem.get("schema_match_score", 0.0),
        mem.get("hours_since_creation", 24.0),
    )

    return {**mem, "replay_priority": priority}


# ── Metrics ──────────────────────────────────────────────────────────────


def compute_transfer_metrics(memories: list[dict]) -> dict:
    """Compute aggregate hippocampal-cortical transfer metrics."""
    if not memories:
        return {
            "total": 0,
            "hippocampal": 0,
            "transitional": 0,
            "cortical": 0,
            "avg_dependency": 0.0,
            "transfer_progress": 0.0,
        }

    deps = [m.get("hippocampal_dependency", 1.0) for m in memories]
    stages = [m.get("consolidation_stage", "labile") for m in memories]

    stores = [classify_memory_store(d, s) for d, s in zip(deps, stages)]

    avg_dep = sum(deps) / len(deps)
    progress = sum(1 for s in stores if s == "cortical") / len(stores)

    return {
        "total": len(memories),
        "hippocampal": stores.count("hippocampal"),
        "transitional": stores.count("transitional"),
        "cortical": stores.count("cortical"),
        "avg_dependency": round(avg_dep, 4),
        "transfer_progress": round(progress, 4),
    }
