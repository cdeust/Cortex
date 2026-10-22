"""Coupled neuromodulation — cross-channel modulatory cascade.

source: ADR-0154"""

from __future__ import annotations

from dataclasses import dataclass

from mcp_server.core.neuromodulation_channels import (
    ACH_ALPHA,
    DA_ALPHA,
    NE_ALPHA,
    apply_cross_coupling,
    compute_dopamine_rpe,
    compute_norepinephrine_arousal,
    compute_serotonin_exploration,
)
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

# ── Neuromodulatory State ────────────────────────────────────────────────


@dataclass
class NeuromodulatoryState:
    """Dynamic state of the 4-channel modulatory system.

    source: ADR-0154"""

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

    if is_mechanism_disabled(Mechanism.NEUROMODULATION):
        # No-op: state is frozen at the current values; no DA/NE/ACh/5-HT updates.
        return current

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
    """DA scales LTP rate via proportional gain (base * channel / baseline)."""
    return base_rate * da


def modulate_precision_gain(base_precision: float, ne: float) -> float:
    """NE scales precision via proportional gain (base * channel / baseline)."""
    return base_precision * ne


def modulate_write_gate_threshold(base_threshold: float, ne: float) -> float:
    """NE lowers write gate under arousal via inverse proportional gain."""
    return base_threshold / max(ne, 0.01)


def modulate_spreading_breadth(base_breadth: int, ser: float) -> int:
    """5-HT scales spreading activation breadth via proportional gain."""
    return max(1, round(base_breadth * ser))


# source: ADR-0154
_CASCADE_GATE_THRESHOLD = 0.7


def compute_cascade_gate(da: float, importance: float) -> bool:
    """DA gates consolidation advancement.

    source: ADR-0154
    """
    return (da * importance) > _CASCADE_GATE_THRESHOLD


# ── Composite Modulation ────────────────────────────────────────────────


def compute_composite_modulation(state: NeuromodulatoryState) -> dict[str, float]:
    """Compute composite modulation via equal-weight combination.

    source: ADR-0154
    """
    da, ne, ach, ser = (
        state.dopamine,
        state.norepinephrine,
        state.acetylcholine,
        state.serotonin,
    )

    # source: ADR-0154
    n = 4
    composite = (da + ne + ach + ser) / n

    return {
        "dopamine": da,
        "norepinephrine": ne,
        "acetylcholine": ach,
        "serotonin": ser,
        "heat_modulation": round(composite, 4),
        "importance_modulation": round(composite, 4),
        "decay_modulation": round(composite, 4),
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
