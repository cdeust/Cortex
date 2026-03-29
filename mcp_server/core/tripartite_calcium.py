"""Tripartite synapse calcium dynamics, D-serine modulation, and metabolic gating.

Split from tripartite_synapse.py for the 300-line file limit. Contains the
computational primitives for calcium rise/decay/propagation, calcium regime
classification, LTP modulation via D-serine, heterosynaptic depression, and
metabolic rate computation.

References:
    Perea G, Navarrete M, Araque A (2009) Tripartite synapses: astrocytes
        process and control synaptic information. Trends Neurosci 32:421-431
    De Pitta M et al. (2012) Computational quest for understanding the role
        of astrocyte signaling in synaptic transmission and plasticity.
        Front Comp Neurosci 6:98
    Henneberger C et al. (2010) Long-term potentiation depends on release
        of D-serine from astrocytes. Nature 463:232-236

Pure business logic — no I/O.
"""

from __future__ import annotations

import math

# ── Configuration ─────────────────────────────────────────────────────────

# Calcium thresholds for different modulation regimes
CA_LOW_THRESHOLD = 0.3
CA_MEDIUM_THRESHOLD = 0.6

# Calcium dynamics
CA_RISE_RATE = 0.15
CA_DECAY_RATE = 0.05
CA_WAVE_SPREAD = 0.3

# Modulation strengths
DSERINE_LTP_BOOST = 0.2
GLUT_LTD_STRENGTH = 0.15

# Metabolic constants
METABOLIC_BASELINE = 1.0
METABOLIC_BOOST = 1.5
METABOLIC_STARVATION = 0.6


# ── Calcium Dynamics ─────────────────────────────────────────────────────


def compute_calcium_rise(
    current_calcium: float,
    synaptic_events: int,
    *,
    rise_rate: float = CA_RISE_RATE,
) -> float:
    """Compute calcium rise from synaptic activity.

    Each synaptic event raises Ca2+. Saturates at 1.0.
    """
    rise = rise_rate * synaptic_events * (1.0 - current_calcium)
    return min(1.0, current_calcium + rise)


def compute_calcium_decay(
    current_calcium: float,
    hours_elapsed: float,
    *,
    decay_rate: float = CA_DECAY_RATE,
) -> float:
    """Compute passive calcium decay (pump-mediated clearance)."""
    if hours_elapsed <= 0:
        return current_calcium
    return current_calcium * math.exp(-decay_rate * hours_elapsed)


def propagate_calcium_wave(
    source_calcium: float,
    neighbor_calciums: list[float],
    *,
    spread_factor: float = CA_WAVE_SPREAD,
) -> list[float]:
    """Propagate calcium wave from active territory to neighbors.

    IP3-mediated propagation through gap junctions.
    """
    if source_calcium < CA_LOW_THRESHOLD:
        return list(neighbor_calciums)

    wave_amount = source_calcium * spread_factor
    return [min(1.0, nc + wave_amount * (1.0 - nc)) for nc in neighbor_calciums]


# ── Synaptic Modulation ────────────────────────────────────────────────


def classify_calcium_regime(calcium: float) -> str:
    """Classify calcium level into modulation regime.

    Returns:
        "quiescent", "facilitation", or "depression".
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
    """Compute LTP rate modulation from astrocyte calcium.

    Facilitation regime: D-serine co-agonist potentiates NMDA -> LTP boost.
    Depression regime: glutamate causes heterosynaptic LTD.

    Returns:
        LTP multiplier. >1 = facilitated, <1 = depressed.
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
    """Compute depression adjustment for a single memory."""
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
    """Compute heterosynaptic depression across a territory.

    High Ca2+ causes glutamate release that depresses less-active synapses,
    preventing one memory from dominating the territory.

    Returns:
        Heat adjustment factors (multiply with current heat).
    """
    if calcium < CA_MEDIUM_THRESHOLD or not memory_heats:
        return [1.0] * len(memory_heats)

    depression_factor = (calcium - CA_MEDIUM_THRESHOLD) / (1.0 - CA_MEDIUM_THRESHOLD)
    avg_heat = sum(memory_heats) / len(memory_heats)

    return [
        _compute_heat_adjustment(h, avg_heat, depression_factor, depression_strength)
        for h in memory_heats
    ]


# ── Metabolic Gating ────────────────────────────────────────────────────


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
    """Compute metabolic support rate for a territory.

    Active territories get more support (lactate shuttle). Inactive
    territories get starved (faster decay).

    Returns:
        Metabolic rate [min_rate, max_boost].
    """
    if time_hours <= 0:
        return baseline

    density = total_activity / time_hours
    return _compute_activity_rate(density, baseline, max_boost, min_rate)


def apply_metabolic_modulation(
    base_decay_factor: float,
    metabolic_rate: float,
) -> float:
    """Apply metabolic rate to decay factor.

    High metabolic rate -> slower decay. Low -> faster decay.
    """
    decay_distance = 1.0 - base_decay_factor
    adjusted = decay_distance / max(metabolic_rate, 0.1)
    return max(0.0, min(1.0, 1.0 - adjusted))
