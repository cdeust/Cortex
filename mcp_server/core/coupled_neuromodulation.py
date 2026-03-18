"""Coupled neuromodulation — cross-channel modulatory cascade.

Orchestrates the 4-channel neuromodulatory system where channels influence each
other and gate downstream mechanisms. Individual channel computations live in
neuromodulation_channels.py; this module owns NeuromodulatoryState, the update
orchestrator, downstream modulation functions, and serialization.

Coupling architecture (Doya 2002):
  DA -> gates cascade.py stage advancement (protein synthesis signal)
  DA -> modulates synaptic_plasticity LTP rate (reward-dependent learning)
  NE -> modulates predictive coding precision gain (attention/arousal)
  NE -> modulates write gate threshold (urgency -> lower gate)
  ACh -> driven by oscillatory_clock theta phase (encoding/retrieval mode)
  ACh -> gates which hierarchy level dominates in predictive coding
  5-HT -> modulates spreading_activation breadth (exploration vs exploitation)
  5-HT -> softmax temperature for retrieval ranking

References:
    Doya K (2002) Metalearning and neuromodulation.
        Neural Networks 15:495-506
    Schultz W (1997) Dopamine neurons and their role in reward mechanisms.
        Curr Opin Neurobiol 7:191-197
    Aston-Jones G, Cohen JD (2005) An integrative theory of locus
        coeruleus-norepinephrine function. Annu Rev Neurosci 28:403-450

Pure business logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from mcp_server.core.neuromodulation_channels import (
    DA_ALPHA,
    NE_ALPHA,
    ACH_ALPHA,
    apply_cross_coupling,
    compute_dopamine_rpe,
    compute_norepinephrine_arousal,
    compute_serotonin_exploration,
)


# ── Neuromodulatory State ────────────────────────────────────────────────


@dataclass
class NeuromodulatoryState:
    """Dynamic state of the 4-channel modulatory system.

    All levels in [0, 2] with 1.0 = baseline (no modulation).
    """

    dopamine: float = 1.0
    norepinephrine: float = 1.0
    acetylcholine: float = 1.0
    serotonin: float = 1.0
    da_baseline: float = 0.5
    ne_adaptation: float = 0.0


# ── Per-Operation Events ─────────────────────────────────────────────────


@dataclass
class OperationSignals:
    """Signals from a single memory operation that drive neuromodulation."""

    error_encountered: bool = False
    error_resolved: bool = False
    test_passed: bool = False
    test_failed: bool = False
    novel_entities: int = 0
    total_entities: int = 0
    theta_phase: float = 0.0
    ach_from_theta: float = 0.5
    schema_match: float = 0.0
    memory_importance: float = 0.5


# ── State Update (per-operation) ─────────────────────────────────────────


def _compute_acetylcholine(signals: OperationSignals) -> float:
    """Compute ACh from theta phase and entity novelty."""
    ach_theta = signals.ach_from_theta
    novelty_boost = (
        signals.novel_entities / max(signals.total_entities, 1) * 0.3
        if signals.total_entities > 0
        else 0.0
    )
    return ach_theta + novelty_boost


def _compute_raw_channels(
    current: NeuromodulatoryState,
    signals: OperationSignals,
) -> tuple[float, float, float, float, float, float]:
    """Compute raw channel values before EMA blending."""
    da, new_baseline = compute_dopamine_rpe(
        outcome_positive=(signals.error_resolved or signals.test_passed),
        outcome_negative=(signals.error_encountered or signals.test_failed),
        memory_importance=signals.memory_importance,
        da_baseline=current.da_baseline,
    )
    ne, new_adaptation = compute_norepinephrine_arousal(
        signals.error_encountered,
        current.norepinephrine,
        current.ne_adaptation,
    )
    ach = _compute_acetylcholine(signals)
    ser = compute_serotonin_exploration(
        signals.schema_match,
        signals.novel_entities,
        signals.total_entities,
        current.serotonin,
    )
    return da, ne, ach, ser, new_baseline, new_adaptation


def update_state(
    current: NeuromodulatoryState,
    signals: OperationSignals,
) -> NeuromodulatoryState:
    """Advance neuromodulatory state by one operation.

    Takes current state + operation signals, returns new state with all
    channels updated and cross-coupled. Original not mutated.
    """
    da, ne, ach, ser, new_baseline, new_adaptation = _compute_raw_channels(
        current, signals
    )

    # EMA blend with current state
    da = current.dopamine + DA_ALPHA * (da - current.dopamine)
    ne = current.norepinephrine + NE_ALPHA * (ne - current.norepinephrine)
    ach = current.acetylcholine + ACH_ALPHA * (ach - current.acetylcholine)
    da, ne, ach, ser = apply_cross_coupling(da, ne, ach, ser)

    return NeuromodulatoryState(
        dopamine=round(da, 4),
        norepinephrine=round(ne, 4),
        acetylcholine=round(ach, 4),
        serotonin=round(ser, 4),
        da_baseline=round(new_baseline, 4),
        ne_adaptation=round(new_adaptation, 4),
    )


# ── Downstream Modulation ────────────────────────────────────────────────


def modulate_ltp_rate(base_rate: float, da: float) -> float:
    """DA gates LTP rate: positive RPE -> stronger learning."""
    return base_rate * (0.5 + 0.5 * da)


def modulate_precision_gain(base_precision: float, ne: float) -> float:
    """NE modulates precision (gain control) in predictive coding."""
    return base_precision * (0.5 + 0.5 * ne)


def modulate_write_gate_threshold(base_threshold: float, ne: float) -> float:
    """NE modulates write gate threshold: high arousal -> lower bar."""
    return base_threshold * (1.5 - 0.5 * min(ne, 2.0))


def modulate_spreading_breadth(base_breadth: int, ser: float) -> int:
    """5-HT modulates spreading activation breadth."""
    factor = 0.5 + 0.5 * ser
    return max(1, round(base_breadth * factor))


def modulate_retrieval_temperature(base_temp: float, ser: float) -> float:
    """5-HT modulates retrieval softmax temperature."""
    return base_temp * (0.5 + 0.5 * ser)


def compute_cascade_gate(da: float, importance: float) -> bool:
    """DA gates consolidation stage advancement (protein synthesis)."""
    return (da * importance) > 0.7


# ── Composite Modulation (backward-compatible) ───────────────────────────


def compute_composite_modulation(state: NeuromodulatoryState) -> dict[str, float]:
    """Compute composite modulation signals from full state."""
    da, ne, ach, ser = (
        state.dopamine,
        state.norepinephrine,
        state.acetylcholine,
        state.serotonin,
    )

    heat_mod = da * 0.4 + ne * 0.3 + ach * 0.3
    importance_mod = da * 0.5 + (2.0 - ser) * 0.3 + ne * 0.2
    decay_mod = ne * 0.3 + ach * 0.3 + da * 0.2 + (2.0 - ser) * 0.2

    return {
        "dopamine": da,
        "norepinephrine": ne,
        "acetylcholine": ach,
        "serotonin": ser,
        "heat_modulation": round(heat_mod, 4),
        "importance_modulation": round(importance_mod, 4),
        "decay_modulation": round(decay_mod, 4),
        "cascade_gate": compute_cascade_gate(da, 0.5),
    }


# ── Serialization ────────────────────────────────────────────────────────


def state_to_dict(state: NeuromodulatoryState) -> dict:
    """Serialize neuromodulatory state to dict."""
    return {
        "dopamine": state.dopamine,
        "norepinephrine": state.norepinephrine,
        "acetylcholine": state.acetylcholine,
        "serotonin": state.serotonin,
        "da_baseline": state.da_baseline,
        "ne_adaptation": state.ne_adaptation,
    }


def state_from_dict(data: dict) -> NeuromodulatoryState:
    """Deserialize neuromodulatory state from dict."""
    return NeuromodulatoryState(
        dopamine=data.get("dopamine", 1.0),
        norepinephrine=data.get("norepinephrine", 1.0),
        acetylcholine=data.get("acetylcholine", 1.0),
        serotonin=data.get("serotonin", 1.0),
        da_baseline=data.get("da_baseline", 0.5),
        ne_adaptation=data.get("ne_adaptation", 0.0),
    )
