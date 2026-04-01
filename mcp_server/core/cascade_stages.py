"""Consolidation cascade — stage definitions, properties, decay, and serialization.

Models the biochemical cascade that transforms a labile memory trace into a
stable, cortically integrated engram. Memories progress through stages with
different properties at each stage:

Stages:
  LABILE (0-1h)         — Just encoded. Highly vulnerable to interference.
  EARLY_LTP (1-6h)      — Synaptic tag set (Frey & Morris 1997).
  LATE_LTP (6-24h)      — Protein synthesis complete. CREB-dependent.
  CONSOLIDATED (>24h)   — Systems consolidation underway.
  RECONSOLIDATING       — Retrieval-triggered lability (Nader et al. 2000).

Each stage has:
  - A decay rate multiplier (labile decays fast, consolidated decays slow)
  - An interference vulnerability (labile = high, consolidated = low)
  - A plasticity level (how modifiable the trace is)
  - A minimum dwell time (can't skip stages)
  - Transition requirements (what must be true to advance)

References:
    Kandel ER (2001) The molecular biology of memory storage.
    Dudai Y (2012) The restless engram: consolidations never end.
    Frey U, Morris RGM (1997) Synaptic tagging and LTP. Nature 385:533-536
    Nader K et al. (2000) Fear memories require protein synthesis in the
        amygdala for reconsolidation after retrieval. Nature 406:722-726

Pure business logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConsolidationStage(Enum):
    """Memory consolidation stages, ordered by maturity."""

    LABILE = "labile"
    EARLY_LTP = "early_ltp"
    LATE_LTP = "late_ltp"
    CONSOLIDATED = "consolidated"
    RECONSOLIDATING = "reconsolidating"


# ── Stage Properties ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageProperties:
    """Immutable properties for each consolidation stage.

    Attributes:
        decay_multiplier: Multiplied into decay rate. >1 = faster decay, <1 = slower.
        interference_vulnerability: How susceptible to interference [0, 1].
        plasticity: How modifiable the memory is [0, 1].
        min_dwell_hours: Minimum time in this stage before advancement.
        max_dwell_hours: Maximum time before forced transition (or decay).
        heat_floor: Minimum heat for this stage. Consolidated memories never
            decay below this floor. Based on Bahrick (1984) permastore effect
            and Benna & Fusi (2016) cascade retention floors.
    """

    decay_multiplier: float
    interference_vulnerability: float
    plasticity: float
    min_dwell_hours: float
    max_dwell_hours: float
    heat_floor: float


_STAGE_PROPERTIES: dict[ConsolidationStage, StageProperties] = {
    # LABILE: No structural substrate yet. Fully vulnerable to decay.
    # Biological: post-translational modifications only (minutes).
    ConsolidationStage.LABILE: StageProperties(
        decay_multiplier=2.0,
        interference_vulnerability=0.9,
        plasticity=1.0,
        min_dwell_hours=0.0,
        max_dwell_hours=1.0,
        heat_floor=0.0,  # Can decay to zero — no structural support
    ),
    # EARLY_LTP: Synaptic tag set but protein synthesis not yet complete.
    # Biological: PKA/CaMKII activation (1-6h). Reversible.
    ConsolidationStage.EARLY_LTP: StageProperties(
        decay_multiplier=1.2,
        interference_vulnerability=0.5,
        plasticity=0.7,
        min_dwell_hours=1.0,
        max_dwell_hours=6.0,
        heat_floor=0.0,  # Still reversible — no guaranteed retention
    ),
    # LATE_LTP: CREB-dependent protein synthesis complete. Structural changes
    # beginning. Blocked by anisomycin only if applied within first 1-3h window.
    # Biological: new protein synthesis, initial synapse growth (6-24h).
    ConsolidationStage.LATE_LTP: StageProperties(
        decay_multiplier=0.8,
        interference_vulnerability=0.2,
        plasticity=0.3,
        min_dwell_hours=6.0,
        max_dwell_hours=24.0,
        heat_floor=0.05,  # Partial structural support — won't fully vanish
    ),
    # CONSOLIDATED: Structural consolidation complete (Kandel 2001: at 72h,
    # blocking protein synthesis has NO effect — synaptic changes are permanent).
    # Bahrick (1984): permastore — retained for 30+ years without rehearsal.
    # Benna & Fusi (2016): deepest cascade levels provide irreversible storage.
    ConsolidationStage.CONSOLIDATED: StageProperties(
        decay_multiplier=0.5,
        interference_vulnerability=0.05,
        plasticity=0.1,
        min_dwell_hours=24.0,
        max_dwell_hours=float("inf"),
        heat_floor=0.10,  # Permastore: always retrievable (Bahrick 1984)
    ),
    # RECONSOLIDATING: Retrieved memory becomes labile again (Nader 2000).
    # Needs re-stabilization via protein synthesis.
    ConsolidationStage.RECONSOLIDATING: StageProperties(
        decay_multiplier=1.5,
        interference_vulnerability=0.8,
        plasticity=0.9,
        min_dwell_hours=0.0,
        max_dwell_hours=6.0,
        heat_floor=0.05,  # Was consolidated — retains partial structural support
    ),
}


def get_stage_properties(stage: ConsolidationStage) -> StageProperties:
    """Get properties for a consolidation stage."""
    return _STAGE_PROPERTIES[stage]


def get_stage_properties_by_name(stage_name: str) -> StageProperties:
    """Get properties by stage name string. Returns LABILE properties for unknown stages."""
    try:
        stage = ConsolidationStage(stage_name)
        return _STAGE_PROPERTIES[stage]
    except (ValueError, KeyError):
        return _STAGE_PROPERTIES[ConsolidationStage.LABILE]


def get_heat_floor(stage_name: str) -> float:
    """Get minimum heat for a consolidation stage (Bahrick 1984 permastore).

    Consolidated memories never decay below this floor. The structural
    substrate (new synapses, enlarged spines — Kandel 2001) persists
    even without rehearsal.
    """
    props = get_stage_properties_by_name(stage_name)
    return props.heat_floor


# ── Decay Integration ─────────────────────────────────────────────────────


def compute_stage_adjusted_decay(
    base_decay_factor: float,
    current_stage: str,
) -> float:
    """Adjust decay factor based on consolidation stage.

    Labile memories decay faster. Consolidated memories decay slower.

    Args:
        base_decay_factor: Base per-hour decay factor (e.g., 0.95).
        current_stage: Current consolidation stage name.

    Returns:
        Stage-adjusted decay factor. Higher = slower decay.
    """
    props = get_stage_properties_by_name(current_stage)
    decay_distance = 1.0 - base_decay_factor
    adjusted_distance = decay_distance * props.decay_multiplier
    return max(0.0, min(1.0, 1.0 - adjusted_distance))


def compute_interference_resistance(
    current_stage: str,
    similarity_to_interferer: float,
) -> float:
    """Compute how much a memory resists interference from a similar new memory.

    Returns resistance score [0, 1]. 0 = no resistance, 1 = full resistance.

    Args:
        current_stage: Current consolidation stage name.
        similarity_to_interferer: Cosine similarity to the interfering memory [0, 1].

    Returns:
        Interference resistance score.
    """
    props = get_stage_properties_by_name(current_stage)
    vulnerability = props.interference_vulnerability
    raw_threat = similarity_to_interferer * vulnerability
    resistance = 1.0 - raw_threat
    return max(0.0, min(1.0, resistance))


# ── Serialization ─────────────────────────────────────────────────────────


def stage_to_dict(
    stage: str,
    hours_in_stage: float,
    replay_count: int = 0,
) -> dict:
    """Serialize consolidation state for storage."""
    props = get_stage_properties_by_name(stage)
    return {
        "stage": stage,
        "hours_in_stage": round(hours_in_stage, 2),
        "replay_count": replay_count,
        "decay_multiplier": props.decay_multiplier,
        "interference_vulnerability": props.interference_vulnerability,
        "plasticity": props.plasticity,
    }
