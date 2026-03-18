"""Individual neuromodulator channel computations.

Computes per-channel updates for the 4 neuromodulatory channels (DA, NE, ACh, 5-HT)
and their cross-coupling interactions. Split from coupled_neuromodulation.py for the
300-line file limit.

Channel architecture (Doya 2002):
  DA: Reward prediction error (Rescorla-Wagner)
  NE: Arousal/urgency with habituation
  ACh: Encoding/retrieval mode (theta-driven)
  5-HT: Exploration/exploitation balance

Cross-coupling:
  DA ↔ NE: High DA dampens NE (success reduces arousal)
  NE → ACh: High NE boosts ACh (arousal enhances encoding)
  5-HT ↔ DA: High 5-HT dampens DA (exploration dampens reward)
  ACh → 5-HT: High ACh dampens 5-HT (learning reduces exploration)

References:
    Doya K (2002) Metalearning and neuromodulation.
        Neural Networks 15:495-506
    Schultz W (1997) Dopamine neurons and their role in reward mechanisms.
        Curr Opin Neurobiol 7:191-197
    Yu AJ, Dayan P (2005) Uncertainty, neuromodulation, and attention.
        Neuron 46:681-692

Pure business logic — no I/O.
"""

from __future__ import annotations


# ── EMA rates for each channel ──────────────────────────────────────────

DA_ALPHA = 0.3  # DA responds quickly to RPE
NE_ALPHA = 0.2  # NE responds moderately
ACH_ALPHA = 0.4  # ACh closely tracks theta phase
SER_ALPHA = 0.15  # 5-HT changes slowly (mood-like)

# ── Cross-coupling strengths ────────────────────────────────────────────

_DA_NE_COUPLING = -0.15  # High DA dampens NE
_NE_ACH_COUPLING = 0.2  # High NE boosts ACh
_SER_DA_COUPLING = -0.1  # High 5-HT dampens DA sensitivity
_ACH_SER_COUPLING = -0.15  # High ACh dampens 5-HT

# ── Habituation constants ──────────────────────────────────────────────

NE_HABITUATION_RATE = 0.05
NE_HABITUATION_DECAY = 0.02


# ── Channel Computation Functions ──────────────────────────────────────


def compute_dopamine_rpe(
    outcome_positive: bool,
    outcome_negative: bool,
    memory_importance: float,
    da_baseline: float,
) -> tuple[float, float]:
    """Compute dopamine RPE signal and updated baseline.

    True Rescorla-Wagner: RPE = actual_reward - expected_reward.
    Positive RPE -> DA burst. Negative RPE -> DA dip.
    Baseline adapts to predict average reward.

    Returns:
        (da_level, updated_baseline).
    """
    if outcome_positive:
        actual = 0.7 + memory_importance * 0.3
    elif outcome_negative:
        actual = 0.2 - memory_importance * 0.1
    else:
        actual = 0.5

    rpe = actual - da_baseline
    da = max(0.3, min(2.0, 1.0 + rpe * 1.5))

    new_baseline = da_baseline + 0.1 * (actual - da_baseline)
    new_baseline = max(0.1, min(0.9, new_baseline))

    return da, new_baseline


def compute_norepinephrine_arousal(
    error_encountered: bool,
    current_ne: float,
    ne_adaptation: float,
) -> tuple[float, float]:
    """Compute NE arousal level with habituation.

    Repeated errors gradually reduce NE response (habituation).
    Novel errors produce strong NE burst.
    Absence of errors lets NE decay toward baseline.

    Returns:
        (ne_level, updated_adaptation).
    """
    if error_encountered:
        burst = 0.5 * (1.0 - ne_adaptation)
        ne = min(2.0, current_ne + burst)
        new_adapt = min(0.8, ne_adaptation + NE_HABITUATION_RATE)
    else:
        ne = current_ne + 0.1 * (1.0 - current_ne)
        new_adapt = max(0.0, ne_adaptation - NE_HABITUATION_DECAY)

    return max(0.3, min(2.0, ne)), new_adapt


def compute_serotonin_exploration(
    schema_match: float,
    novel_entities: int,
    total_entities: int,
    current_ser: float,
) -> float:
    """Compute 5-HT exploration/exploitation signal.

    High schema match -> exploitation (5-HT low).
    Many novel entities -> exploration (5-HT high).

    Returns:
        Updated 5-HT level.
    """
    novelty_ratio = (
        novel_entities / max(total_entities, 1) if total_entities > 0 else 0.5
    )
    exploitation_signal = schema_match

    target = 0.5 + novelty_ratio * 0.8 - exploitation_signal * 0.5
    target = max(0.3, min(1.8, target))

    return current_ser + SER_ALPHA * (target - current_ser)


def apply_cross_coupling(
    da: float,
    ne: float,
    ach: float,
    ser: float,
) -> tuple[float, float, float, float]:
    """Apply inter-channel coupling effects.

    DA <-> NE: Success dampens arousal
    NE -> ACh: Arousal enhances novelty detection
    5-HT <-> DA: Exploration dampens reward signal
    ACh -> 5-HT: Learning mode reduces exploration

    Returns:
        Post-coupling (da, ne, ach, ser).
    """
    ne_coupled = ne + _DA_NE_COUPLING * (da - 1.0)
    ach_coupled = ach + _NE_ACH_COUPLING * (ne - 1.0)
    da_coupled = da + _SER_DA_COUPLING * (ser - 1.0)
    ser_coupled = ser + _ACH_SER_COUPLING * (ach - 1.0)

    return (
        max(0.3, min(2.0, da_coupled)),
        max(0.3, min(2.0, ne_coupled)),
        max(0.3, min(2.0, ach_coupled)),
        max(0.3, min(2.0, ser_coupled)),
    )
