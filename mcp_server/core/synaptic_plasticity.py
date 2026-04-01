"""Synaptic plasticity — Tsodyks-Markram STP, phase gating, and public API.

Tsodyks-Markram short-term plasticity (Tsodyks & Markram 1997, "The neural
code between neocortical pyramidal neurons depends on neurotransmitter
release probability", PNAS 94:719-723; Markram et al. 1998):

  At each spike event:
    u_eff = u + U * (1 - u)        (facilitation: residual Ca2+ boost)
    x_new = x - u_eff * x          (depression: vesicle depletion)

  Between spikes (continuous recovery):
    du/dt = -u / tau_F              (facilitation decays, tau_F ~ 530ms)
    dx/dt = (1 - x) / tau_D        (vesicles recover, tau_D ~ 130ms)

  Effective release = u_eff * x (utilization * available resources)

  Timescale adaptation: biological tau_F ~ 530ms, tau_D ~ 130ms.
  Adapted to hours: tau_F = 0.5h (30min facilitation), tau_D = 2.0h
  (2h vesicle recovery). This is a documented departure — ratio preserved.

Phase-gated plasticity: LTP/LTD magnitude is modulated by theta phase
(Hasselmo 2005). Encoding phase amplifies LTP; retrieval phase suppresses it.

Re-exports Hebbian/STDP functions from synaptic_plasticity_hebbian.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# -- Tsodyks-Markram STP Constants (adapted timescale) -------------------------

# U: baseline utilization increment per spike (Tsodyks & Markram 1997)
# Biological range: 0.15-0.5 depending on synapse type
_U_INCREMENT: float = 0.2

# tau_F: facilitation time constant. Biological: ~530ms.
# Adapted to hours: 0.5h (30min) — residual Ca2+ decays over ~30 min.
_TAU_F_HOURS: float = 0.5

# tau_D: depression recovery time constant. Biological: ~130ms.
# Adapted to hours: 2.0h — vesicle replenishment takes ~2h.
_TAU_D_HOURS: float = 2.0

_NOISE_SCALE: float = 0.01

# -- Weight Bounds (shared with hebbian module) --------------------------------

_MIN_WEIGHT: float = 0.01
_MAX_WEIGHT: float = 2.0


# -- Synaptic State (Tsodyks-Markram) ------------------------------------------


@dataclass
class SynapticState:
    """Per-edge Tsodyks-Markram STP state.

    u: utilization parameter (facilitation). Starts at 0, boosted by U on
       each spike, decays with tau_F. Represents residual Ca2+ in terminal.
    x: available resources (1 = full vesicle pool, 0 = depleted). Starts at 1,
       depleted by u*x on each spike, recovers with tau_D.
    access_count: for noise scaling (Bayesian evidence accumulation).
    hours_since_last_access: for continuous recovery between spikes.
    """

    u: float = 0.0
    x: float = 1.0
    access_count: int = 0
    hours_since_last_access: float = 0.0


# -- Release Probability (Tsodyks-Markram) -------------------------------------


def compute_effective_release_probability(state: SynapticState) -> float:
    """Effective release: u_eff * x (Tsodyks-Markram 1997).

    u_eff = U + u * (1 - U): facilitation-boosted utilization.
    x: available vesicle fraction.
    Product gives transmission probability, clamped to [0.05, 0.95].
    """
    u_eff = _U_INCREMENT + state.u * (1.0 - _U_INCREMENT)
    p_eff = u_eff * state.x
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


# -- Tsodyks-Markram Dynamics --------------------------------------------------


def update_short_term_dynamics(
    state: SynapticState,
    hours_elapsed: float,
    is_access: bool = False,
) -> SynapticState:
    """Tsodyks-Markram STP update (Tsodyks & Markram 1997).

    Between spikes (continuous recovery):
      u(t) = u0 * exp(-t / tau_F)
      x(t) = 1 - (1 - x0) * exp(-t / tau_D)

    At spike (discrete update):
      u_new = u + U * (1 - u)      (facilitation boost)
      x_new = x - u_new * x        (vesicle depletion)

    Returns new SynapticState (original not mutated).
    """
    u, x = _recover_between_spikes(state.u, state.x, hours_elapsed)

    access_count = state.access_count
    hours_since = hours_elapsed

    if is_access:
        u, x, access_count, hours_since = _apply_spike(u, x, access_count)

    return SynapticState(
        u=round(u, 6),
        x=round(x, 6),
        access_count=access_count,
        hours_since_last_access=hours_since,
    )


def _recover_between_spikes(
    u: float,
    x: float,
    hours_elapsed: float,
) -> tuple[float, float]:
    """Continuous recovery: u decays to 0, x recovers to 1.

    Tsodyks-Markram 1997, between-spike analytical solution:
      u(t) = u0 * exp(-t / tau_F)
      x(t) = 1 - (1 - x0) * exp(-t / tau_D)
    """
    if hours_elapsed <= 0:
        return u, x

    u_new = u * math.exp(-hours_elapsed / _TAU_F_HOURS)
    x_new = 1.0 - (1.0 - x) * math.exp(-hours_elapsed / _TAU_D_HOURS)
    return u_new, x_new


def _apply_spike(
    u: float,
    x: float,
    access_count: int,
) -> tuple[float, float, int, float]:
    """Spike event: facilitation boost + vesicle depletion.

    Tsodyks-Markram 1997:
      u_new = u + U * (1 - u)    (residual Ca2+ increment)
      x_new = x - u_new * x      (release depletes available resources)
    """
    u_new = u + _U_INCREMENT * (1.0 - u)
    x_new = x - u_new * x
    x_new = max(0.0, x_new)
    return u_new, x_new, access_count + 1, 0.0


# -- Noise Injection -----------------------------------------------------------


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


# -- Phase-Gated Plasticity (Hasselmo 2005) ------------------------------------


def phase_modulate_plasticity(
    delta_w: float,
    theta_phase: float,
    is_ltp: bool = True,
) -> float:
    """Modulate plasticity magnitude by theta phase (Hasselmo 2005).

    Encoding phase (0.0-0.5): LTP amplified, LTD suppressed.
    Retrieval phase (0.5-1.0): LTP suppressed, LTD amplified.
    Cosine envelope for smooth transition.
    """
    raw = math.cos(2.0 * math.pi * (theta_phase - 0.25))
    encoding_strength = 0.65 + 0.35 * raw

    if is_ltp:
        return delta_w * encoding_strength

    retrieval_strength = 0.65 - 0.35 * raw
    return delta_w * retrieval_strength


# -- Re-exports from sub-modules -----------------------------------------------

from mcp_server.core.synaptic_plasticity_hebbian import (  # noqa: E402
    apply_hebbian_update,
    apply_stdp_batch,
    compute_bcm_phi,
    compute_ltd,
    compute_ltp,
    compute_stdp_update,
    update_bcm_threshold,
)
from mcp_server.core.synaptic_plasticity_stochastic import (  # noqa: E402
    apply_stochastic_hebbian_update,
)

__all__ = [
    "SynapticState",
    "compute_effective_release_probability",
    "stochastic_transmit",
    "update_short_term_dynamics",
    "compute_noisy_weight_update",
    "phase_modulate_plasticity",
    "compute_bcm_phi",
    "compute_ltp",
    "compute_ltd",
    "update_bcm_threshold",
    "apply_hebbian_update",
    "compute_stdp_update",
    "apply_stdp_batch",
    "apply_stochastic_hebbian_update",
]
