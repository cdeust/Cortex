"""Individual neuromodulator channel computations.

Computes per-channel updates for the 4 neuromodulatory channels (DA, NE, ACh, 5-HT)
and their cross-coupling interactions.

What Doya (2002) actually says:
  DA -> temporal discount factor (gamma in RL value estimation)
  NE -> inverse temperature in softmax policy (exploration/exploitation)
  ACh -> learning rate for value function updates
  5-HT -> time scale of reward prediction

What this module implements (departures from Doya noted):
  DA: Reward prediction error signal (Rescorla & Wagner 1972; Schultz 1997).
      Rescorla-Wagner: delta_V = alpha_cs * beta_us * (lambda - V_total).
      In single-CS form: V(s) := V(s) + alpha*beta * (actual - V(s)).
      Current code uses combined alpha*beta = 0.1 (within standard simulation
      range [0.01-0.25]; Daw 2011, Sutton & Barto 1998).
      DA level = 1.0 + delta, clamped to [0.0, 3.0].
      Floor 0.0: DA neurons cannot fire below zero (Schultz 1997, Fig 1-3).
      Ceiling 3.0: baseline tonic ~5 Hz, phasic burst ~20-30 Hz (~4-6x
      baseline; Schultz 1997; Ljungberg et al. 1992; Mirenowicz & Schultz
      1994). Using 3x as conservative upper bound (full 5-6x would make
      positive RPE dominate downstream effects disproportionately).
      The actual-reward heuristic (0.7+importance*0.3 for positive, etc.) is
      an engineering translation — Schultz used juice rewards, not memory ops.

  NE: Arousal/urgency with habituation.
      Inspired by Aston-Jones & Cohen (2005) tonic/phasic LC framework,
      simplified to burst/decay for hours timescale. Aston-Jones proposes
      tonic vs phasic LC modes driven by utility monitoring — a full
      implementation would require task-utility tracking. This code captures
      the qualitative behavior: errors trigger phasic bursts (attenuated by
      habituation), absence of errors returns to tonic baseline.

  ACh: Encoding/retrieval mode from theta phase.
      FAITHFUL to Hasselmo (2005): high ACh during encoding, low during
      retrieval. Theta phase is externally provided.

  5-HT: Exploration/exploitation from novelty vs schema match.
      Engineering translation of Dayan & Huys (2009) behavioral inhibition
      concept. Dayan & Huys show 5-HT opposes impulsive responding and
      promotes behavioral inhibition / exploitation of known structure.
      The direction is qualitatively correct: high novelty -> exploration
      (high 5-HT), high schema match -> exploitation (low 5-HT). The
      specific formula is an engineering approximation — no paper provides
      an equation mapping novelty/schema to 5-HT level.

Cross-coupling: Engineering heuristic coupling. The directions are qualitatively
  plausible (high DA dampens NE per success reducing arousal, high NE boosts ACh
  per arousal enhancing encoding, high 5-HT dampens DA per inhibition reducing
  reward sensitivity, high ACh dampens 5-HT per encoding reducing exploration)
  but specific coupling constants are hand-tuned. No paper provides these
  equations or values.

EMA rates: Ordered to reflect biological response timescales.
  ACH_ALPHA=0.4 — ACh closely tracks theta oscillations (fast, ~200ms cycle)
  DA_ALPHA=0.3  — DA RPE responses are rapid (~100ms phasic bursts, Schultz 1997)
  NE_ALPHA=0.2  — LC phasic responses are moderate (~seconds, Aston-Jones 2005)
  SER_ALPHA=0.15 — 5-HT changes slowly (minutes/hours, tonic modulation)
  The ordering matches biology; absolute values are hand-tuned for this system's
  per-operation update cadence (hours timescale, not milliseconds).

References:
    Rescorla RA, Wagner AR (1972) A theory of Pavlovian conditioning:
        Variations in the effectiveness of reinforcement and nonreinforcement.
        In: Black AH, Prokasy WF (Eds.), Classical Conditioning II, pp. 64-99.
        (RPE equation: delta_V = alpha * beta * (lambda - V_total))
    Schultz W (1997) A neural substrate of prediction and reward.
        Science 275:1593-1599 (DA firing rate data: ~5 Hz tonic, ~20-30 Hz burst)
    Schultz W, Dayan P, Montague PR (1997) A neural substrate of prediction
        and reward. Science 275:1593-1599 (TD error: delta = r + gamma*V(s') - V(s);
        this code uses R-W not TD — appropriate for discrete memory operations)
    Doya K (2002) Metalearning and neuromodulation.
        Neural Networks 15:495-506 (framework inspiration, not faithfully implemented)
    Aston-Jones G, Cohen JD (2005) An integrative theory of locus
        coeruleus-norepinephrine function. Annu Rev Neurosci 28:403-450
        (tonic/phasic concept; full model not implemented)
    Hasselmo ME (2005) What is the function of hippocampal theta rhythm?
        Hippocampus 15:936-949
    Dayan P, Huys QJM (2009) Serotonin in affective control.
        Annu Rev Neurosci 32:95-126 (behavioral inhibition concept;
        no specific equation implemented)

Pure business logic — no I/O.
"""

from __future__ import annotations

# ── EMA rates for each channel ──────────────────────────────────────────
# Ordered by biological response speed. See module docstring for rationale.

DA_ALPHA = 0.3  # DA phasic RPE bursts (~100ms in biology)
NE_ALPHA = 0.2  # LC phasic responses (~seconds in biology)
ACH_ALPHA = 0.4  # ACh tracks theta oscillations (~200ms cycle)
SER_ALPHA = 0.15  # 5-HT tonic modulation (minutes/hours in biology)

# ── Cross-coupling strengths ────────────────────────────────────────────
# Engineering heuristic. Directions are qualitatively plausible but specific
# values are hand-tuned. No paper provides these coupling equations.

_DA_NE_COUPLING = -0.15  # High DA dampens NE (success reduces arousal)
_NE_ACH_COUPLING = 0.2  # High NE boosts ACh (arousal enhances encoding)
_SER_DA_COUPLING = -0.1  # High 5-HT dampens DA (inhibition reduces reward sensitivity)
_ACH_SER_COUPLING = -0.15  # High ACh dampens 5-HT (encoding reduces exploration)

# ── Habituation constants ──────────────────────────────────────────────
# Engineering values for NE habituation (repeated stressors reduce response).

NE_HABITUATION_RATE = 0.05
NE_HABITUATION_DECAY = 0.02


# ── Channel Computation Functions ──────────────────────────────────────


def compute_dopamine_rpe(
    outcome_positive: bool,
    outcome_negative: bool,
    memory_importance: float,
    da_baseline: float,
) -> tuple[float, float]:
    """Rescorla-Wagner RPE (Rescorla & Wagner 1972; Schultz 1997).

    Implements single-CS Rescorla-Wagner:
      delta = actual - V(s)                    (prediction error)
      V(s) := V(s) + alpha*beta * delta        (learning rule)
      DA = 1.0 + delta                         (firing rate mapping)

    Combined alpha*beta = 0.1 — hand-tuned within standard simulation
    range [0.01-0.25] (Daw 2011, Sutton & Barto 1998). In R-W theory,
    alpha = CS salience, beta = US intensity; here they are merged since
    each memory operation has a single stimulus context.

    Clamped to [0.0, 3.0]:
      Floor 0.0 — DA neurons cannot fire below zero (Schultz 1997).
      Ceiling 3.0 — conservative bound. Biology: baseline ~5 Hz, burst
      ~20-30 Hz = ~4-6x (Schultz 1997, Ljungberg et al. 1992). Using
      3x to avoid positive RPE dominating downstream modulation.

    The actual-reward mapping (positive/negative/neutral -> numeric value)
    is an engineering translation of Schultz's juice/airpuff paradigm.

    Returns:
        (da_level, updated_baseline).
    """
    # Hand-tuned reward mapping — no paper provides this translation.
    if outcome_positive:
        actual = 0.7 + memory_importance * 0.3
    elif outcome_negative:
        actual = 0.2 - memory_importance * 0.1
    else:
        actual = 0.5

    # Rescorla-Wagner: delta = lambda - V(s)
    delta = actual - da_baseline
    # Schultz: DA firing = baseline * (1 + delta), clamped to [0, 3x baseline]
    da = max(0.0, min(3.0, 1.0 + delta))

    # Rescorla-Wagner: V(s) := V(s) + alpha*beta * (actual - V(s))
    # Combined alpha*beta = 0.1 (hand-tuned, within standard range)
    new_baseline = da_baseline + 0.1 * (actual - da_baseline)
    new_baseline = max(0.1, min(0.9, new_baseline))

    return da, new_baseline


def compute_norepinephrine_arousal(
    error_encountered: bool,
    current_ne: float,
    ne_adaptation: float,
) -> tuple[float, float]:
    """Arousal model inspired by Aston-Jones & Cohen (2005) tonic/phasic LC framework.

    Simplified to burst/decay for hours timescale. Aston-Jones proposes tonic vs
    phasic LC modes driven by utility monitoring — this code captures the
    qualitative behavior without the full utility-tracking model.

    Errors trigger phasic NE burst (attenuated by habituation, modeling
    repeated-stressor adaptation). Absence of errors decays NE toward tonic
    baseline (1.0). All numeric constants are hand-tuned.

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
    """Exploration/exploitation signal — engineering translation of Dayan & Huys (2009).

    Dayan & Huys show 5-HT opposes impulsive responding and promotes behavioral
    inhibition. This translates to: high schema match promotes exploitation
    (lower 5-HT), high novelty promotes exploration (higher 5-HT). The
    direction is qualitatively consistent with the paper; the specific formula
    and coefficients are engineering approximations.

    Returns:
        Updated 5-HT level (EMA-blended with current).
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
    """Linear additive cross-coupling — engineering heuristic.

    Coupling directions are qualitatively plausible:
      DA dampens NE — success reduces arousal.
      NE boosts ACh — arousal enhances encoding.
      5-HT dampens DA — inhibition reduces reward sensitivity.
      ACh dampens 5-HT — encoding reduces exploration.
    Specific coupling constants are hand-tuned. No paper provides these
    equations or values.

    Returns:
        Post-coupling (da, ne, ach, ser).
    """
    ne_coupled = ne + _DA_NE_COUPLING * (da - 1.0)
    ach_coupled = ach + _NE_ACH_COUPLING * (ne - 1.0)
    da_coupled = da + _SER_DA_COUPLING * (ser - 1.0)
    ser_coupled = ser + _ACH_SER_COUPLING * (ach - 1.0)

    return (
        max(0.0, min(3.0, da_coupled)),  # DA: asymmetric [0, 3] per Schultz 1997
        max(0.3, min(2.0, ne_coupled)),
        max(0.3, min(2.0, ach_coupled)),
        max(0.3, min(2.0, ser_coupled)),
    )
