"""Tripartite synapse calcium dynamics via De Pitta et al. (2009) G-ChI model.

Reference: De Pitta M et al. (2009) Glutamate regulation of calcium and IP3
oscillating and pulsating dynamics in astrocytes. J Biol Phys 35:383-411

ODE system (Li-Rinzel reduction, Eq. 5-8):
    dC/dt = J_chan + J_leak - J_pump
    dh/dt = (h_inf - h) / tau_h
    J_chan = r_C * m_inf^3 * h * (I/(I+d_1)) * (C_0 - C) / c_1
    J_leak = r_L * (C_0 - C) / c_1
    J_pump = v_ER * C^2 / (K_ER^2 + C^2)
    m_inf = I/(I+d_1) * C/(C+d_5)
    h_inf = d_2*(I+d_1) / ((I+d_3)*(C+d_2))

Timescale: biological Ca2+ transients complete in seconds. Our system operates
at hours. We compute the steady-state equilibrium Ca2+ as f(IP3), not the
transient. At steady state dC/dt=0, dh/dt=0.

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math

# ── De Pitta 2009 Parameters (Table 1, AM mode) ─────────────────────────

R_C = 6.0  # s^-1, maximal CICR rate
R_L = 0.11  # s^-1, ER leak rate
C_0 = 2.0  # uM, total cell calcium
C_1 = 0.185  # cytosol/ER volume ratio
V_ER = 0.9  # uM/s, SERCA max pump rate
K_ER = 0.1  # uM, SERCA affinity
D_1 = 0.13  # uM, IP3 binding dissociation
D_2 = 1.049  # uM, Ca2+ inactivation dissociation
D_3 = 0.9434  # uM, IP3 dissociation (inhibiting)
D_5 = 0.08234  # uM, Ca2+ activation dissociation
A_2 = 0.2  # s^-1, IP3R inactivation rate

# ── System mapping constants (not from paper) ───────────────────────────

IP3_PER_EVENT = 0.15  # uM IP3 per synaptic event
IP3_MAX = 2.0  # uM, saturation ceiling
CA_RESTING_UM = 0.54  # uM, resting Ca2+ from De Pitta at IP3=0
CA_RANGE_UM = 1.0  # uM, dynamic range above resting -> [0, 1]

# Regime thresholds (De Pitta bifurcation, normalized scale)
CA_LOW_THRESHOLD = 0.3
CA_MEDIUM_THRESHOLD = 0.6

# Modulation strengths (qualitative, no parametric paper model)
DSERINE_LTP_BOOST = 0.2
GLUT_LTD_STRENGTH = 0.15

# Metabolic constants (Pellerin & Magistretti 1994 concept)
METABOLIC_BASELINE = 1.0
METABOLIC_BOOST = 1.5
METABOLIC_STARVATION = 0.6


# ── De Pitta Steady-State Solver ─────────────────────────────────────────


def _h_inf(ip3: float, ca: float) -> float:
    """Steady-state inactivation variable (Li-Rinzel / De Pitta)."""
    denom = (ip3 + D_3) * (ca + D_2)
    if denom < 1e-15:
        return 1.0
    return D_2 * (ip3 + D_1) / denom


def _m_inf(ip3: float, ca: float) -> float:
    """Steady-state activation: IP3 fraction * Ca2+ fraction."""
    ip3_frac = ip3 / (ip3 + D_1) if (ip3 + D_1) > 1e-15 else 0.0
    ca_frac = ca / (ca + D_5) if (ca + D_5) > 1e-15 else 0.0
    return ip3_frac * ca_frac


def _j_pump(ca: float) -> float:
    """SERCA pump flux: Hill function with n=2."""
    return V_ER * ca**2 / (K_ER**2 + ca**2)


def _j_leak(ca: float) -> float:
    """ER leak flux."""
    return R_L * (C_0 - ca) / C_1


def _j_chan(ip3: float, ca: float, h: float) -> float:
    """IP3R channel flux."""
    m = _m_inf(ip3, ca)
    ip3_frac = ip3 / (ip3 + D_1) if (ip3 + D_1) > 1e-15 else 0.0
    return R_C * m**3 * h * ip3_frac * (C_0 - ca) / C_1


def _steady_state_calcium(ip3: float, *, max_iter: int = 200) -> float:
    """Find equilibrium Ca2+ for given IP3 via Euler forward iteration.

    Sets h = h_inf at each step (quasi-steady-state) and iterates dC/dt
    until convergence. Returns Ca2+ in uM.
    """
    ca = 0.05
    dt = 0.05  # virtual seconds per step (for convergence only)
    for _ in range(max_iter):
        h = _h_inf(ip3, ca)
        flux = _j_chan(ip3, ca, h) + _j_leak(ca) - _j_pump(ca)
        ca_new = max(0.001, min(C_0 * 0.95, ca + flux * dt))
        if abs(ca_new - ca) < 1e-6:
            return ca_new
        ca = ca_new
    return ca


# ── Calcium Dynamics ─────────────────────────────────────────────────────


def _synaptic_events_to_ip3(events: int) -> float:
    """Map synaptic events to IP3 (uM) with Michaelis-Menten saturation."""
    raw = IP3_PER_EVENT * events
    return IP3_MAX * raw / (IP3_MAX + raw) if raw > 0 else 0.0


def _normalize_calcium(ca_um: float) -> float:
    """Convert Ca2+ (uM) to [0, 1]. Resting (~0.54 uM) maps to 0."""
    return min(1.0, max(0.0, (ca_um - CA_RESTING_UM) / CA_RANGE_UM))


def compute_calcium_rise(
    current_calcium: float,
    synaptic_events: int,
) -> float:
    """Compute Ca2+ after activity via De Pitta 2009 steady state.

    Maps events -> IP3, solves G-ChI equilibrium, blends toward it.
    """
    if synaptic_events <= 0:
        return current_calcium
    ip3 = _synaptic_events_to_ip3(synaptic_events)
    eq_normalized = _normalize_calcium(_steady_state_calcium(ip3))
    approach_rate = 1.0 - math.exp(-0.3 * synaptic_events)
    new_ca = current_calcium + approach_rate * (eq_normalized - current_calcium)
    return min(1.0, max(0.0, new_ca))


def compute_calcium_decay(
    current_calcium: float,
    hours_elapsed: float,
) -> float:
    """Decay toward resting Ca2+ (IP3=0 steady state, normalized to 0).

    At hours timescale, biological transients have long completed.
    Exponential relaxation toward resting equilibrium.
    """
    if hours_elapsed <= 0:
        return current_calcium
    resting = _normalize_calcium(_steady_state_calcium(0.0))
    decay_rate = 0.1  # per hour (system-tuned)
    alpha = 1.0 - math.exp(-decay_rate * hours_elapsed)
    return max(0.0, current_calcium + alpha * (resting - current_calcium))


def propagate_calcium_wave(
    source_calcium: float,
    neighbor_calciums: list[float],
    *,
    spread_factor: float = 0.3,
) -> list[float]:
    """Threshold-gated linear Ca2+ spread to neighbors.

    Engineering approximation; biological waves involve regenerative IP3.
    """
    if source_calcium < CA_LOW_THRESHOLD:
        return list(neighbor_calciums)
    wave_amount = source_calcium * spread_factor
    return [min(1.0, nc + wave_amount * (1.0 - nc)) for nc in neighbor_calciums]


# ── Synaptic Modulation ──────────────────────────────────────────────────


def classify_calcium_regime(calcium: float) -> str:
    """Classify normalized Ca2+ into quiescent/facilitation/depression.

    Thresholds at 0.3 and 0.6 on normalized scale, informed by
    De Pitta 2009 bifurcation structure.
    """
    if calcium < CA_LOW_THRESHOLD:
        return "quiescent"
    if calcium < CA_MEDIUM_THRESHOLD:
        return "facilitation"
    return "depression"


def compute_ltp_modulation(
    calcium: float,
    *,
    d_serine_boost: float = DSERINE_LTP_BOOST,
) -> float:
    """LTP modulation by regime. Qualitative from Henneberger (2010).

    No parametric dose-response exists; linear ramps are engineering choices.
    Returns multiplier: >1 facilitated, <1 depressed.
    """
    regime = classify_calcium_regime(calcium)
    if regime == "quiescent":
        return 1.0
    if regime == "facilitation":
        t = (calcium - CA_LOW_THRESHOLD) / (CA_MEDIUM_THRESHOLD - CA_LOW_THRESHOLD)
        return 1.0 + d_serine_boost * t
    t = (calcium - CA_MEDIUM_THRESHOLD) / (1.0 - CA_MEDIUM_THRESHOLD)
    return max(0.5, 1.0 - GLUT_LTD_STRENGTH * t)


def _compute_heat_adjustment(
    heat: float,
    avg_heat: float,
    depression_factor: float,
    depression_strength: float,
) -> float:
    """Depression adjustment for a single memory."""
    if heat >= avg_heat:
        adj = 1.0 - depression_strength * depression_factor * 0.2
    else:
        adj = 1.0 - depression_strength * depression_factor * (1.0 - heat)
    return max(0.5, adj)


def compute_heterosynaptic_depression(
    calcium: float,
    memory_heats: list[float],
    *,
    depression_strength: float = GLUT_LTD_STRENGTH,
) -> list[float]:
    """Depression across territory: high Ca2+ depresses less-active synapses."""
    if calcium < CA_MEDIUM_THRESHOLD or not memory_heats:
        return [1.0] * len(memory_heats)
    depression_factor = (calcium - CA_MEDIUM_THRESHOLD) / (1.0 - CA_MEDIUM_THRESHOLD)
    avg_heat = sum(memory_heats) / len(memory_heats)
    return [
        _compute_heat_adjustment(h, avg_heat, depression_factor, depression_strength)
        for h in memory_heats
    ]


# ── Metabolic Gating (Pellerin & Magistretti 1994) ──────────────────────


def _compute_activity_rate(
    density: float,
    baseline: float,
    max_boost: float,
    min_rate: float,
) -> float:
    """Map activity density to metabolic rate via sigmoid response."""
    if density > 1.0:
        rate = baseline + (max_boost - baseline) * (
            1.0 - math.exp(-(density - 1.0) / 3.0)
        )
    else:
        rate = min_rate + (baseline - min_rate) * density
    return max(min_rate, min(max_boost, rate))


def compute_metabolic_rate(
    total_activity: float,
    time_hours: float,
    *,
    baseline: float = METABOLIC_BASELINE,
    max_boost: float = METABOLIC_BOOST,
    min_rate: float = METABOLIC_STARVATION,
) -> float:
    """Metabolic support rate. Active territories get more resources."""
    if time_hours <= 0:
        return baseline
    density = total_activity / time_hours
    return _compute_activity_rate(density, baseline, max_boost, min_rate)


def apply_metabolic_modulation(
    base_decay_factor: float,
    metabolic_rate: float,
) -> float:
    """High metabolic rate -> slower decay. Low -> faster decay."""
    decay_distance = 1.0 - base_decay_factor
    adjusted = decay_distance / max(metabolic_rate, 0.1)
    return max(0.0, min(1.0, 1.0 - adjusted))
