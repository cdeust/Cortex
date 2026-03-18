"""Synaptic plasticity -- stochastic transmission, phase gating, and public API.

Stochastic synaptic transmission (Markram et al. 1998, Abbott & Regehr 2004):
Real synapses are probabilistic. Each edge has a release probability p that
determines whether a signal propagates. Short-term facilitation increases p
on repeated use; short-term depression depletes vesicles and decreases p.

Phase-gated plasticity: LTP/LTD magnitude is modulated by theta phase
(Hasselmo 2005). Encoding phase amplifies LTP; retrieval phase suppresses it.

Re-exports Hebbian/STDP functions from synaptic_plasticity_hebbian for
backward compatibility.

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# -- Stochastic Transmission Defaults ----------------------------------------

_BASE_RELEASE_PROB: float = 0.5
_FACILITATION_RATE: float = 0.15
_FACILITATION_DECAY: float = 0.9
_DEPRESSION_RATE: float = 0.2
_DEPRESSION_DECAY: float = 0.85
_DEPRESSION_INTERVAL_HOURS: float = 0.5
_NOISE_SCALE: float = 0.01

# -- Weight Bounds (shared with hebbian module) -------------------------------

_MIN_WEIGHT: float = 0.01
_MAX_WEIGHT: float = 2.0


# -- Synaptic State -----------------------------------------------------------


@dataclass
class SynapticState:
    """Per-edge stochastic transmission state.

    Tracks release probability, short-term facilitation/depression,
    and access history for noise scaling.
    """

    release_probability: float = _BASE_RELEASE_PROB
    facilitation: float = 0.0
    depression: float = 0.0
    access_count: int = 0
    hours_since_last_access: float = 0.0


# -- Release Probability ------------------------------------------------------


def compute_effective_release_probability(state: SynapticState) -> float:
    """Compute effective release probability after facilitation/depression.

    p_eff = p_base + facilitation - depression, clamped to [0.05, 0.95].
    """
    p_eff = state.release_probability + state.facilitation - state.depression
    return max(0.05, min(0.95, p_eff))


def stochastic_transmit(
    state: SynapticState,
    rng: random.Random | None = None,
) -> bool:
    """Determine if a synaptic signal propagates (probabilistic).

    Returns True with probability = effective release probability.
    """
    p = compute_effective_release_probability(state)
    r = (rng or random).random()
    return r < p


# -- Short-Term Dynamics -------------------------------------------------------


def update_short_term_dynamics(
    state: SynapticState,
    hours_elapsed: float,
    is_access: bool = False,
) -> SynapticState:
    """Update short-term facilitation and depression.

    On access: facilitation increases; rapid access triggers depression.
    Over time: both facilitation and depression decay exponentially.
    Returns new SynapticState (immutable update).
    """
    fac, dep = _decay_facilitation_depression(
        state.facilitation,
        state.depression,
        hours_elapsed,
    )
    access_count = state.access_count
    hours_since = hours_elapsed

    if is_access:
        fac, dep, access_count, hours_since = _apply_access(
            fac,
            dep,
            access_count,
            state.hours_since_last_access,
        )

    return SynapticState(
        release_probability=state.release_probability,
        facilitation=round(fac, 6),
        depression=round(dep, 6),
        access_count=access_count,
        hours_since_last_access=hours_since,
    )


def _decay_facilitation_depression(
    facilitation: float,
    depression: float,
    hours_elapsed: float,
) -> tuple[float, float]:
    """Decay facilitation and depression over elapsed time."""
    if hours_elapsed <= 0:
        return facilitation, depression

    fac = facilitation * (_FACILITATION_DECAY**hours_elapsed)
    dep = depression * (_DEPRESSION_DECAY**hours_elapsed)
    return fac, dep


def _apply_access(
    facilitation: float,
    depression: float,
    access_count: int,
    hours_since_last_access: float,
) -> tuple[float, float, int, float]:
    """Apply access effects: boost facilitation, maybe trigger depression."""
    facilitation = min(1.0, facilitation + _FACILITATION_RATE)

    if hours_since_last_access < _DEPRESSION_INTERVAL_HOURS:
        depression = min(1.0, depression + _DEPRESSION_RATE)

    return facilitation, depression, access_count + 1, 0.0


# -- Noise Injection ----------------------------------------------------------


def compute_noisy_weight_update(
    delta_w: float,
    access_count: int,
    noise_scale: float = _NOISE_SCALE,
    rng: random.Random | None = None,
) -> float:
    """Add Gaussian noise to a weight update, scaled by 1/sqrt(evidence).

    More observations (higher access_count) -> less noise -> more stable updates.
    """
    if access_count <= 0:
        evidence_factor = 1.0
    else:
        evidence_factor = 1.0 / math.sqrt(access_count)

    sigma = noise_scale * evidence_factor
    noise = (rng or random).gauss(0.0, sigma)
    return delta_w + noise


# -- Phase-Gated Plasticity ---------------------------------------------------


def phase_modulate_plasticity(
    delta_w: float,
    theta_phase: float,
    is_ltp: bool = True,
) -> float:
    """Modulate plasticity magnitude by theta phase.

    Encoding phase (0.0-0.5): LTP amplified, LTD suppressed.
    Retrieval phase (0.5-1.0): LTP suppressed, LTD amplified.
    Uses cosine envelope matching oscillatory_clock.compute_encoding_strength.
    """
    raw = math.cos(2.0 * math.pi * (theta_phase - 0.25))
    encoding_strength = 0.65 + 0.35 * raw

    if is_ltp:
        return delta_w * encoding_strength

    retrieval_strength = 0.65 - 0.35 * raw
    return delta_w * retrieval_strength


# -- Hebbian/STDP functions (used by phase_modulate_plasticity) ----------------

from mcp_server.core.synaptic_plasticity_hebbian import (  # noqa: E402
    apply_hebbian_update,
    apply_stdp_batch,
    compute_ltp,
    compute_ltd,
    compute_stdp_update,
    update_bcm_threshold,
)
from mcp_server.core.synaptic_plasticity_stochastic import (  # noqa: E402
    apply_stochastic_hebbian_update,
)

__all__ = [
    # Stochastic transmission
    "SynapticState",
    "compute_effective_release_probability",
    "stochastic_transmit",
    "update_short_term_dynamics",
    "compute_noisy_weight_update",
    "phase_modulate_plasticity",
    # From hebbian module
    "compute_ltp",
    "compute_ltd",
    "update_bcm_threshold",
    "apply_hebbian_update",
    "compute_stdp_update",
    "apply_stdp_batch",
    "apply_stochastic_hebbian_update",
]
