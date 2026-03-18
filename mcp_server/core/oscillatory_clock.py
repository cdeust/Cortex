"""Oscillatory clock — state transitions, modulation, and serialization.

Manages the OscillatoryClock state machine: theta advancement, gamma binding,
SWR lifecycle, and phase-gated modulation of encoding/retrieval/plasticity.

Pure business logic — no I/O. State is passed in and returned; persistence
handled by the caller.
"""

from __future__ import annotations

from mcp_server.core.oscillatory_phases import (
    OscillatoryState,
    SWR_BURST_STEPS,
    SWR_REFRACTORY_STEPS,
    SWRState,
    compute_ach_from_phase,
    compute_encoding_strength,
    compute_retrieval_strength,
)

__all__ = [
    "OscillatoryState",
    "SWRState",
    "compute_encoding_strength",
    "compute_retrieval_strength",
    "compute_ach_from_phase",
    "advance_theta",
    "advance_gamma",
    "begin_swr",
    "step_swr",
    "is_swr_active",
    "modulate_encoding",
    "modulate_retrieval",
    "modulate_plasticity",
    "state_to_dict",
    "state_from_dict",
]


# ── State Transitions ─────────────────────────────────────────────────────


def advance_theta(
    state: OscillatoryState,
    operations: int = 1,
    *,
    operations_per_cycle: int = 20,
) -> OscillatoryState:
    """Advance the theta clock by a number of operations.

    Each operation advances the phase by 1/operations_per_cycle. When the
    phase wraps past 1.0, a new theta cycle begins and gamma resets.
    """
    phase_increment = operations / operations_per_cycle
    new_phase = state.theta_phase + phase_increment
    new_cycles = state.theta_cycles_total + int(new_phase)
    new_phase = new_phase % 1.0

    gamma_count = (
        state.gamma_count if int(state.theta_phase + phase_increment) == 0 else 0
    )

    return OscillatoryState(
        theta_phase=round(new_phase, 6),
        gamma_count=gamma_count,
        swr_state=state.swr_state,
        swr_steps_remaining=state.swr_steps_remaining,
        theta_cycles_total=new_cycles,
        operations_since_swr=state.operations_since_swr + operations,
        hours_since_last_swr=state.hours_since_last_swr,
        ach_level=round(compute_ach_from_phase(new_phase), 4),
    )


def advance_gamma(state: OscillatoryState) -> OscillatoryState:
    """Record a gamma binding event (one item bound)."""
    return OscillatoryState(
        theta_phase=state.theta_phase,
        gamma_count=state.gamma_count + 1,
        swr_state=state.swr_state,
        swr_steps_remaining=state.swr_steps_remaining,
        theta_cycles_total=state.theta_cycles_total,
        operations_since_swr=state.operations_since_swr,
        hours_since_last_swr=state.hours_since_last_swr,
        ach_level=state.ach_level,
    )


def begin_swr(state: OscillatoryState) -> OscillatoryState:
    """Transition to SWR (sharp-wave ripple) state."""
    return OscillatoryState(
        theta_phase=state.theta_phase,
        gamma_count=state.gamma_count,
        swr_state=SWRState.RIPPLE.value,
        swr_steps_remaining=SWR_BURST_STEPS,
        theta_cycles_total=state.theta_cycles_total,
        operations_since_swr=0,
        hours_since_last_swr=0.0,
        ach_level=state.ach_level,
    )


def _next_swr_state(swr_state: str, remaining: int) -> tuple[str, int]:
    """Compute the next SWR state and step count after one consolidation step."""
    if swr_state == SWRState.RIPPLE.value:
        remaining -= 1
        if remaining <= 0:
            return SWRState.REFRACTORY.value, SWR_REFRACTORY_STEPS
        return swr_state, remaining

    if swr_state == SWRState.REFRACTORY.value:
        remaining -= 1
        if remaining <= 0:
            return SWRState.QUIESCENT.value, 0
        return swr_state, remaining

    return swr_state, remaining


def step_swr(state: OscillatoryState) -> OscillatoryState:
    """Advance one consolidation step during SWR or refractory period."""
    swr_state, remaining = _next_swr_state(
        state.swr_state,
        state.swr_steps_remaining,
    )

    return OscillatoryState(
        theta_phase=state.theta_phase,
        gamma_count=state.gamma_count,
        swr_state=swr_state,
        swr_steps_remaining=remaining,
        theta_cycles_total=state.theta_cycles_total,
        operations_since_swr=state.operations_since_swr,
        hours_since_last_swr=state.hours_since_last_swr,
        ach_level=state.ach_level,
    )


def is_swr_active(state: OscillatoryState) -> bool:
    """Check if the system is in an active SWR (replay/plasticity enabled)."""
    return state.swr_state == SWRState.RIPPLE.value


# ── Phase-Gated Modulation ────────────────────────────────────────────────


def modulate_encoding(
    base_strength: float,
    state: OscillatoryState,
) -> float:
    """Apply oscillatory modulation to an encoding operation.

    SWR suppresses new encoding (hippocampus busy with replay).
    """
    phase_mod = compute_encoding_strength(state.theta_phase)

    if is_swr_active(state):
        phase_mod *= 0.3

    return base_strength * phase_mod


def modulate_retrieval(
    base_score: float,
    state: OscillatoryState,
) -> float:
    """Apply oscillatory modulation to a retrieval operation."""
    phase_mod = compute_retrieval_strength(state.theta_phase)
    return base_score * phase_mod


def modulate_plasticity(
    base_delta: float,
    state: OscillatoryState,
) -> float:
    """Apply oscillatory modulation to a plasticity update (LTP/LTD).

    During SWR, replay-driven plasticity is boosted.
    Normal operation: phase-dependent.
    """
    if is_swr_active(state):
        return base_delta * 1.5
    return base_delta * compute_encoding_strength(state.theta_phase)


# ── Serialization ─────────────────────────────────────────────────────────


def state_to_dict(state: OscillatoryState) -> dict:
    """Serialize oscillatory state to a JSON-compatible dict."""
    return {
        "theta_phase": state.theta_phase,
        "gamma_count": state.gamma_count,
        "swr_state": state.swr_state,
        "swr_steps_remaining": state.swr_steps_remaining,
        "theta_cycles_total": state.theta_cycles_total,
        "operations_since_swr": state.operations_since_swr,
        "hours_since_last_swr": state.hours_since_last_swr,
        "ach_level": state.ach_level,
    }


def state_from_dict(data: dict) -> OscillatoryState:
    """Deserialize oscillatory state from a dict."""
    return OscillatoryState(
        theta_phase=data.get("theta_phase", 0.0),
        gamma_count=data.get("gamma_count", 0),
        swr_state=data.get("swr_state", "quiescent"),
        swr_steps_remaining=data.get("swr_steps_remaining", 0),
        theta_cycles_total=data.get("theta_cycles_total", 0),
        operations_since_swr=data.get("operations_since_swr", 0),
        hours_since_last_swr=data.get("hours_since_last_swr", 0.0),
        ach_level=data.get("ach_level", 0.8),
    )
