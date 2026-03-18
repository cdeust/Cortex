"""Oscillatory phase computation — theta, gamma, and SWR gating logic.

Models three frequency bands that gate encoding, retrieval, and consolidation:

- **Theta (4-8 Hz)**: Session-level cycles. First half = encoding phase (new memories
  get stronger LTP). Second half = retrieval phase (recall gets spreading activation
  boost). Based on Hasselmo (2005): theta rhythm separates encoding from retrieval
  in hippocampal CA1 via cholinergic modulation.

- **Gamma (30-80 Hz)**: Operation-level binding. Each gamma burst within a theta cycle
  binds one item (memory/entity) into the current representation. Capacity ~7 items
  per theta cycle mirrors Miller's 7+/-2. Based on Lisman & Jensen (2013): gamma
  cycles nested in theta encode ordered sequences.

- **Sharp-Wave Ripples (SWR, 100-200 Hz)**: Consolidation windows. Generated during
  idle/offline periods (consolidation calls). Only during SWR events do replay-driven
  plasticity updates fire. Based on Buzsaki (2015): SWRs compress temporal sequences
  and drive hippocampal-cortical dialogue.

References:
    Hasselmo ME (2005) What is the function of hippocampal theta rhythm?
        Hippocampus 15:936-949
    Lisman JE, Jensen O (2013) The theta-gamma neural code.
        Neuron 77:1002-1016
    Buzsaki G (2015) Hippocampal sharp wave-ripple: A cognitive biomarker
        for episodic memory and planning. Hippocampus 25:1073-1188
    Colgin LL (2013) Mechanisms and functions of theta rhythms.
        Annu Rev Neurosci 36:295-312
    Olafsdottir et al. (2018) The role of hippocampal replay in memory and planning.
        Curr Biol 28:R37-R50

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


# ── Phase Enumerations ────────────────────────────────────────────────────


class ThetaPhase(Enum):
    """Which phase of the theta cycle the system is in.

    Encoding phase (0.0-0.5): High ACh, strong LTP, weak retrieval.
    Retrieval phase (0.5-1.0): Low ACh, weak LTP, strong pattern completion.
    Transition zones near 0.0 and 0.5 blend both modes.
    """

    ENCODING = "encoding"
    RETRIEVAL = "retrieval"
    TRANSITION = "transition"


class SWRState(Enum):
    """Sharp-wave ripple state."""

    QUIESCENT = "quiescent"  # Normal operation, no ripple
    RIPPLE = "ripple"  # Active SWR — replay and plasticity enabled
    REFRACTORY = "refractory"  # Post-ripple cooldown, no new ripple


# ── Constants ────────────────────────────────────────────────────────────

# Transition zone width (fraction of cycle on each side of phase boundary)
TRANSITION_WIDTH = 0.08

# Gamma capacity per theta cycle (Lisman & Jensen: ~7 items)
GAMMA_CAPACITY = 7

# Minimum interval between SWR events (hours)
SWR_MIN_INTERVAL_HOURS = 0.5

# SWR probability increases with accumulated activity since last SWR
SWR_BASE_PROBABILITY = 0.3

# Duration of a single SWR burst (in consolidation steps)
SWR_BURST_STEPS = 5

# Refractory period after SWR (consolidation steps)
SWR_REFRACTORY_STEPS = 3


# ── Oscillatory State ─────────────────────────────────────────────────────


@dataclass
class OscillatoryState:
    """Full oscillatory state of the memory system.

    Pure data object — no side effects. Functions compute state transitions
    and return new states.
    """

    theta_phase: float = 0.0
    gamma_count: int = 0
    swr_state: str = "quiescent"  # Store as string for serialization
    swr_steps_remaining: int = 0
    theta_cycles_total: int = 0
    operations_since_swr: int = 0
    hours_since_last_swr: float = 0.0
    ach_level: float = 0.8  # Start in encoding mode


# ── Theta Phase Logic ─────────────────────────────────────────────────────


def classify_theta_phase(phase: float) -> ThetaPhase:
    """Classify a theta phase value into encoding, retrieval, or transition.

    Phase 0.0-0.5 is encoding (high ACh, strong LTP).
    Phase 0.5-1.0 is retrieval (low ACh, strong pattern completion).
    Narrow bands around 0.0, 0.5 are transitions (blended behavior).
    """
    phase = phase % 1.0

    if phase < TRANSITION_WIDTH or phase > (1.0 - TRANSITION_WIDTH):
        return ThetaPhase.TRANSITION
    if abs(phase - 0.5) < TRANSITION_WIDTH:
        return ThetaPhase.TRANSITION

    if phase < 0.5:
        return ThetaPhase.ENCODING
    return ThetaPhase.RETRIEVAL


def compute_encoding_strength(phase: float) -> float:
    """Compute encoding strength multiplier from theta phase.

    Peak at phase=0.25 (center of encoding half). Smooth cosine envelope.
    Returns value in [0.3, 1.0]. Based on Hasselmo (2005).
    """
    raw = math.cos(2.0 * math.pi * (phase - 0.25))
    return 0.65 + 0.35 * raw


def compute_retrieval_strength(phase: float) -> float:
    """Compute retrieval strength multiplier from theta phase.

    Peak at phase=0.75 (center of retrieval half). Complementary to encoding.
    Returns value in [0.3, 1.0]. Based on Hasselmo (2005).
    """
    raw = math.cos(2.0 * math.pi * (phase - 0.75))
    return 0.65 + 0.35 * raw


def compute_ach_from_phase(phase: float) -> float:
    """Compute acetylcholine level from theta phase.

    High ACh during encoding → favors new learning, suppresses retrieval.
    Low ACh during retrieval → favors pattern completion.
    Returns value in [0.3, 1.0]. Based on Hasselmo (2006).
    """
    raw = math.cos(2.0 * math.pi * (phase - 0.25))
    return 0.65 + 0.35 * raw


# ── Gamma Binding ─────────────────────────────────────────────────────────


def can_bind_item(gamma_count: int, capacity: int = GAMMA_CAPACITY) -> bool:
    """Check if there's gamma capacity to bind another item this theta cycle."""
    return gamma_count < capacity


def gamma_binding_strength(position: int, capacity: int = GAMMA_CAPACITY) -> float:
    """Compute binding strength for the Nth item in a gamma sequence.

    First item gets strongest binding (primacy), last item gets a recency boost.
    Middle items weaken. Models the serial position effect.
    Returns value in [0.5, 1.0].
    """
    if capacity <= 1:
        return 1.0

    primacy = math.exp(-0.5 * position)
    recency = math.exp(-0.5 * (capacity - 1 - position))
    raw = max(primacy, recency)
    return 0.5 + 0.5 * min(raw, 1.0)


# ── Sharp-Wave Ripple Logic ──────────────────────────────────────────────


def _compute_swr_probability(
    operations_since_swr: int,
    hours_since_last_swr: float,
    accumulated_importance: float,
    base_probability: float,
) -> float:
    """Compute SWR trigger probability from contributing factors.

    Combines operation count, importance accumulation, and time pressure
    into a weighted probability score.
    """
    op_factor = min(operations_since_swr / 20.0, 1.0)
    imp_factor = min(accumulated_importance / 5.0, 1.0)
    time_factor = min(hours_since_last_swr / 4.0, 1.0)

    return base_probability * (0.4 * op_factor + 0.3 * imp_factor + 0.3 * time_factor)


def should_generate_swr(
    operations_since_swr: int,
    hours_since_last_swr: float,
    accumulated_importance: float = 0.0,
    *,
    min_interval_hours: float = SWR_MIN_INTERVAL_HOURS,
    base_probability: float = SWR_BASE_PROBABILITY,
) -> bool:
    """Determine whether to generate a sharp-wave ripple event.

    SWR probability increases with operations, time, and importance
    accumulated since the last SWR. Never triggers within refractory interval.
    Deterministic threshold for reproducibility (no randomness in core).
    """
    if hours_since_last_swr < min_interval_hours:
        return False
    if operations_since_swr < 3:
        return False

    probability = _compute_swr_probability(
        operations_since_swr,
        hours_since_last_swr,
        accumulated_importance,
        base_probability,
    )
    return probability >= base_probability * 0.5


def _compute_heat_score(heat: float) -> float:
    """Compute inverted-U heat score for replay priority.

    Moderate heat memories need replay most — too hot means already active,
    too cold means not worth replaying. Peak at heat=0.5.
    """
    return max(0.0, 1.0 - 4.0 * (heat - 0.5) ** 2)


def compute_replay_priority(
    heat: float,
    importance: float,
    surprise: float,
    access_count: int,
    hours_since_creation: float,
) -> float:
    """Compute which memories should be replayed during an SWR event.

    Prioritizes: high importance, moderate heat, high surprise,
    low access count (under-rehearsed), and recent memories.
    Based on Olafsdottir et al. (2018).

    Returns replay priority score [0, 1].
    """
    heat_score = _compute_heat_score(heat)
    rehearsal_need = 1.0 / (1.0 + access_count * 0.5)
    recency = math.exp(-hours_since_creation / 168.0)  # Week time constant

    priority = (
        importance * 0.35
        + heat_score * 0.20
        + surprise * 0.20
        + rehearsal_need * 0.15
        + recency * 0.10
    )
    return min(1.0, max(0.0, priority))
