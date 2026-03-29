"""Stochastic Hebbian LTP/LTD with release probability gating and phase modulation.

Combines stochastic vesicle release, additive noise, and theta-phase gating
with standard Hebbian LTP/LTD rules.

References:
    Hebb (1949), BCM (1982), Markram (1998).

Pure business logic -- no I/O.
"""

from __future__ import annotations

import random
from typing import Any

from mcp_server.core.synaptic_plasticity import (
    _BASE_RELEASE_PROB,
    _MAX_WEIGHT,
    _MIN_WEIGHT,
    SynapticState,
    compute_noisy_weight_update,
    phase_modulate_plasticity,
    stochastic_transmit,
    update_short_term_dynamics,
)
from mcp_server.core.synaptic_plasticity_hebbian import (
    _LTD_RATE,
    _LTP_RATE,
    compute_ltd,
    compute_ltp,
)


def _stochastic_ltp(
    w: float,
    syn: SynapticState,
    src: int,
    tgt: int,
    activities: dict[int, float],
    thresholds: dict[int, float],
    theta_phase: float | None,
    ltp_rate: float,
    rng: random.Random | None,
) -> tuple[float, str]:
    """Stochastic LTP: gate -> compute -> phase-modulate -> add noise."""
    if not stochastic_transmit(syn, rng=rng):
        return w, "blocked"

    new_w = compute_ltp(
        w,
        co_activation=1.0,
        pre_activity=activities.get(src, 0.5),
        post_activity=activities.get(tgt, 0.5),
        theta=thresholds.get(tgt, 0.5),
        ltp_rate=ltp_rate,
    )
    delta = new_w - w
    if theta_phase is not None and delta > 0:
        delta = phase_modulate_plasticity(delta, theta_phase, is_ltp=True)
    delta = compute_noisy_weight_update(delta, syn.access_count, rng=rng)
    new_w = max(_MIN_WEIGHT, min(_MAX_WEIGHT, w + delta))
    return new_w, "ltp" if new_w > w else "none"


def _stochastic_ltd(
    w: float,
    hours: float,
    theta_phase: float | None,
    ltd_rate: float,
) -> tuple[float, str]:
    """LTD with optional phase gating for non-co-accessed edges."""
    new_w = compute_ltd(w, hours, ltd_rate=ltd_rate)
    delta = new_w - w
    if theta_phase is not None and delta < 0:
        delta = phase_modulate_plasticity(delta, theta_phase, is_ltp=False)
        new_w = max(_MIN_WEIGHT, min(_MAX_WEIGHT, w + delta))
    return new_w, "ltd" if new_w < w else "none"


def _build_synaptic_state(edge: dict[str, Any], hours: float) -> SynapticState:
    """Build a SynapticState from edge metadata."""
    return SynapticState(
        release_probability=edge.get("release_probability", _BASE_RELEASE_PROB),
        facilitation=edge.get("facilitation", 0.0),
        depression=edge.get("depression", 0.0),
        access_count=edge.get("access_count", 0),
        hours_since_last_access=edge.get("hours_since_last_access", hours),
    )


def _stochastic_single(
    edge: dict[str, Any],
    co_accessed_pairs: set[tuple[int, int]],
    entity_activities: dict[int, float],
    entity_thresholds: dict[int, float],
    hours: float,
    theta_phase: float | None,
    ltp_rate: float,
    ltd_rate: float,
    rng: random.Random | None,
) -> dict[str, Any]:
    """Process a single edge for stochastic Hebbian update."""
    src, tgt = edge["source_entity_id"], edge["target_entity_id"]
    w = edge.get("weight", 1.0)
    pair = (min(src, tgt), max(src, tgt))
    is_co = pair in co_accessed_pairs

    syn = update_short_term_dynamics(
        _build_synaptic_state(edge, hours), hours, is_access=is_co
    )

    if is_co:
        new_w, action = _stochastic_ltp(
            w,
            syn,
            src,
            tgt,
            entity_activities,
            entity_thresholds,
            theta_phase,
            ltp_rate,
            rng,
        )
    else:
        new_w, action = _stochastic_ltd(w, hours, theta_phase, ltd_rate)

    return {
        **edge,
        "weight": round(new_w, 6),
        "delta": round(new_w - w, 6),
        "action": action,
        "release_probability": syn.release_probability,
        "facilitation": syn.facilitation,
        "depression": syn.depression,
        "access_count": syn.access_count,
    }


def apply_stochastic_hebbian_update(
    edges: list[dict[str, Any]],
    co_accessed_pairs: set[tuple[int, int]],
    entity_activities: dict[int, float],
    entity_thresholds: dict[int, float],
    hours_since_last_update: float = 1.0,
    theta_phase: float | None = None,
    ltp_rate: float = _LTP_RATE,
    ltd_rate: float = _LTD_RATE,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Hebbian LTP/LTD with stochastic gating, noise, and phase modulation."""
    return [
        _stochastic_single(
            edge,
            co_accessed_pairs,
            entity_activities,
            entity_thresholds,
            hours_since_last_update,
            theta_phase,
            ltp_rate,
            ltd_rate,
            rng,
        )
        for edge in edges
    ]
