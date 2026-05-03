"""Hebbian LTP/LTD and STDP updates.

BCM theory (Bienenstock, Cooper & Munro 1982, "Theory for the development
of neuron selectivity", J Neuroscience 2:32-48):
  phi(c, theta_m) = c * (c - theta_m)
  dw/dt = phi(c, theta_m) * d
  theta_m = E[c^2]  (sliding threshold)

  When c > theta_m: phi > 0 → LTP
  When 0 < c < theta_m: phi < 0 → LTD
  theta_m slides up with high activity, down with low activity.

STDP (Bi & Poo 1998, "Synaptic modifications in cultured hippocampal
neurons", J Neuroscience 18:10464-10472):
  Pre-before-post (dt > 0): delta_w = A+ * exp(-dt/tau+)
  Post-before-pre (dt < 0): delta_w = -A- * exp(dt/tau-)
  With A+ > A-, tau+ ≈ 17ms, tau- ≈ 34ms (biological).
  Adapted to hours timescale: tau+ = tau- = 24h.

Constants: _LTP_RATE, _LTD_RATE are overall scaling factors (hand-tuned).
STDP amplitudes A+/A- maintain the A+ > A- asymmetry from Bi & Poo.
Time constants are adapted from ms to hours (documented adaptation).

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
from typing import Any

from mcp_server.core.synaptic_plasticity import (
    _MAX_WEIGHT,
    _MIN_WEIGHT,
)

_LTP_RATE: float = 0.05
_LTD_RATE: float = 0.02
_BCM_THETA_DECAY: float = 0.95
_STDP_A_PLUS: float = 0.03
_STDP_A_MINUS: float = 0.02
_STDP_TAU_PLUS: float = 24.0
_STDP_TAU_MINUS: float = 24.0


def compute_bcm_phi(
    post_activity: float,
    theta: float,
) -> float:
    """BCM quadratic phi function: phi(c, theta_m) = c * (c - theta_m).

    Bienenstock, Cooper & Munro (1982), Eq. 3.
    Returns positive for LTP (c > theta_m), negative for LTD (0 < c < theta_m).
    """
    return post_activity * (post_activity - theta)


def compute_ltp(
    current_weight: float,
    co_activation: float,
    pre_activity: float = 1.0,
    post_activity: float = 1.0,
    theta: float = 0.5,
    ltp_rate: float = _LTP_RATE,
    max_weight: float = _MAX_WEIGHT,
) -> float:
    """BCM LTP: dw = rate * phi(c, theta_m) * d * co_activation.

    phi(c, theta_m) = c * (c - theta_m) — quadratic, per BCM 1982.
    Only applies potentiation (phi > 0); use compute_ltd for depression.
    """
    phi = compute_bcm_phi(post_activity, theta)
    if phi <= 0:
        return current_weight
    delta = ltp_rate * phi * pre_activity * co_activation
    return min(max_weight, current_weight + delta)


def compute_ltd(
    current_weight: float,
    time_since_co_access_hours: float,
    ltd_rate: float = _LTD_RATE,
    min_weight: float = _MIN_WEIGHT,
    post_activity: float = 0.0,
    theta: float = 0.5,
) -> float:
    """BCM LTD: activity-based depression when 0 < c < theta_m.

    Two mechanisms:
    1. Activity-based (BCM 1982): phi(c, theta_m) < 0 when 0 < c < theta_m.
       dw = ltd_rate * phi(c, theta_m).
    2. Inactivity-based (fallback): logarithmic decay for edges with no
       recent co-access. This is engineering heuristic, not from BCM —
       BCM requires postsynaptic activity for LTD.
    """
    if post_activity > 0:
        phi = compute_bcm_phi(post_activity, theta)
        if phi < 0:
            delta = ltd_rate * abs(phi)
            return max(min_weight, current_weight - delta)
        return current_weight

    if time_since_co_access_hours <= 0:
        return current_weight
    decay = ltd_rate * math.log1p(time_since_co_access_hours / 24.0)
    return max(min_weight, current_weight - decay)


def update_bcm_threshold(
    current_theta: float,
    entity_activity: float,
    decay: float = _BCM_THETA_DECAY,
) -> float:
    """BCM sliding threshold: theta_m = E[c^2] (BCM 1982, Eq. 5).

    Implemented as EMA: theta_m' = decay * theta_m + (1 - decay) * c^2.
    This is faithful to BCM theory.
    """
    return decay * current_theta + (1.0 - decay) * (entity_activity**2)


def _hebbian_single(
    edge: dict[str, Any],
    co_accessed_pairs: set[tuple[int, int]],
    entity_activities: dict[int, float],
    entity_thresholds: dict[int, float],
    hours: float,
    ltp_rate: float,
    ltd_rate: float,
) -> dict[str, Any]:
    """Process a single edge for Hebbian LTP or LTD."""
    src, tgt = edge["source_entity_id"], edge["target_entity_id"]
    w = edge.get("weight", 1.0)
    pair = (min(src, tgt), max(src, tgt))

    if pair in co_accessed_pairs:
        new_w = compute_ltp(
            w,
            co_activation=1.0,
            pre_activity=entity_activities.get(src, 0.5),
            post_activity=entity_activities.get(tgt, 0.5),
            theta=entity_thresholds.get(tgt, 0.5),
            ltp_rate=ltp_rate,
        )
        action = "ltp" if new_w > w else "none"
    else:
        new_w = compute_ltd(w, hours, ltd_rate=ltd_rate)
        action = "ltd" if new_w < w else "none"

    return {
        **edge,
        "weight": round(new_w, 6),
        "delta": round(new_w - w, 6),
        "action": action,
    }


def apply_hebbian_update(
    edges: list[dict[str, Any]],
    co_accessed_pairs: set[tuple[int, int]],
    entity_activities: dict[int, float],
    entity_thresholds: dict[int, float],
    hours_since_last_update: float = 1.0,
    ltp_rate: float = _LTP_RATE,
    ltd_rate: float = _LTD_RATE,
) -> list[dict[str, Any]]:
    """Apply Hebbian LTP/LTD to a batch of edges."""
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.SYNAPTIC_PLASTICITY):
        # No-op identity: zero weight change but the result-shape contract
        # (every dict carries `action`, `weight`, `delta`) must hold so
        # downstream `_apply_updates` in handlers/consolidation/plasticity.py
        # doesn't KeyError. Pre-fix returned raw edges, which broke the
        # cycle silently with a logged WARNING and dropped the row's
        # plasticity contribution.
        return [
            {
                **edge,
                "weight": edge.get("weight", 1.0),
                "delta": 0.0,
                "action": "none",
            }
            for edge in edges
        ]
    return [
        _hebbian_single(
            edge,
            co_accessed_pairs,
            entity_activities,
            entity_thresholds,
            hours_since_last_update,
            ltp_rate,
            ltd_rate,
        )
        for edge in edges
    ]


def compute_stdp_update(
    current_weight: float,
    delta_t_hours: float,
    a_plus: float = _STDP_A_PLUS,
    a_minus: float = _STDP_A_MINUS,
    tau_plus: float = _STDP_TAU_PLUS,
    tau_minus: float = _STDP_TAU_MINUS,
    min_weight: float = _MIN_WEIGHT,
    max_weight: float = _MAX_WEIGHT,
) -> float:
    """STDP: dt>0 (pre before post) -> LTP, dt<0 -> LTD."""
    if abs(delta_t_hours) < 0.001:
        return current_weight
    if delta_t_hours > 0:
        delta_w = a_plus * math.exp(-delta_t_hours / tau_plus)
    else:
        delta_w = -a_minus * math.exp(delta_t_hours / tau_minus)
    new_weight = current_weight + delta_w
    return max(min_weight, min(max_weight, round(new_weight, 6)))


def _stdp_single(
    pair: dict[str, Any],
    a_plus: float,
    a_minus: float,
    tau_plus: float,
    tau_minus: float,
) -> dict[str, Any]:
    """Process a single temporal pair for STDP."""
    dt = pair.get("delta_t_hours", 0)
    w = pair.get("current_weight", 1.0)
    new_w = compute_stdp_update(w, dt, a_plus, a_minus, tau_plus, tau_minus)
    if dt > 0.001:
        direction = "causal"
    elif dt < -0.001:
        direction = "anti-causal"
    else:
        direction = "none"
    return {
        "source_entity_id": pair["source_entity_id"],
        "target_entity_id": pair["target_entity_id"],
        "new_weight": new_w,
        "delta": round(new_w - w, 6),
        "direction": direction,
    }


def apply_stdp_batch(
    temporal_pairs: list[dict[str, Any]],
    a_plus: float = _STDP_A_PLUS,
    a_minus: float = _STDP_A_MINUS,
    tau_plus: float = _STDP_TAU_PLUS,
    tau_minus: float = _STDP_TAU_MINUS,
) -> list[dict[str, Any]]:
    """Apply STDP to a batch of temporal entity co-occurrences."""
    return [
        _stdp_single(p, a_plus, a_minus, tau_plus, tau_minus) for p in temporal_pairs
    ]
