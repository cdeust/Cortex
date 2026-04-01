"""Homeostatic plasticity — network-level stability mechanisms.

Without homeostasis, Hebbian learning is unstable: strong memories get stronger
(runaway potentiation), weak memories get weaker (catastrophic depression), and
the system collapses to either all-hot or all-cold. Biology prevents this via
homeostatic mechanisms that maintain target activity levels.

This module implements three homeostatic mechanisms:

1. **Synaptic Scaling (Turrigiano 2008; Tetzlaff et al. 2011)**
   Multiplicative scaling: delta_w = alpha * w * (r_target - r_actual).
   All weights scale proportionally, preserving relative ordering —
   Turrigiano's key experimental finding. The update is proportional to
   the weight itself (multiplicative, not additive).

   Equation from: Tetzlaff C, Kolbe C, Dasgupta S, Bhatt DK (2011)
   "Time scales of memory, learning, and plasticity."
   Frontiers in Computational Neuroscience 5:47, Eq. 3.

   Also: Houweling AR, Bazhenov M, Timofeev I, Steriade M, Bhatt DK (2005)
   "Homeostatic synaptic plasticity can explain post-traumatic epileptogenesis."
   Cerebral Cortex 15:834-845:  delta_G = epsilon * (f_target - f_actual) * G

2. **Metaplasticity / BCM Threshold (Abraham & Bear 1996)**
   Sliding modification threshold: theta_M = E[c^2].
   BCM phi function: phi(c, theta_m) = c * (c - theta_m).
   Bienenstock, Cooper & Munro (1982), J Neuroscience 2:32-48.

3. **Intrinsic Excitability Regulation**
   Engineering heuristic (no paper source). Adjusts global excitability
   toward a target active fraction. Hand-tuned gain of 0.1.

References:
    Turrigiano GG (2008) The self-tuning neuron. Cell 135:422-435
    Tetzlaff C et al. (2011) Time scales of memory, learning, and plasticity.
        Frontiers in Computational Neuroscience 5:47
    Houweling AR et al. (2005) Cerebral Cortex 15:834-845
    Abraham WC, Bear MF (1996) Metaplasticity. Trends Neurosci 19:126-130
    Bienenstock EL, Cooper LN, Munro PW (1982) Theory for the development
        of neuron selectivity. J Neuroscience 2:32-48

Pure business logic — no I/O.
"""

from __future__ import annotations

# ── Configuration ─────────────────────────────────────────────────────────

# Target mean heat for synaptic scaling.  Hand-tuned for Cortex memory system.
_TARGET_HEAT = 0.4

# Scaling rate alpha in delta_w = alpha * w * (r_target - r_actual).
# Hand-tuned: 0.05 gives gentle convergence (~20 cycles to halve a deviation).
_SCALING_RATE = 0.05

# BCM threshold EMA decay.  Hand-tuned: 0.95 gives ~20-step memory.
_BCM_THETA_DECAY = 0.95

# Excitability bounds.  Hand-tuned engineering heuristic.
_MIN_GLOBAL_EXCITABILITY = 0.1
_MAX_GLOBAL_EXCITABILITY = 0.9

# Target fraction of engram slots that should be "active" (excitability >= 0.5).
# Hand-tuned engineering heuristic.
_TARGET_ACTIVE_FRACTION = 0.3


# ── Synaptic Scaling (Turrigiano 2008; Tetzlaff et al. 2011) ─────────────


def compute_scaling_factor(
    current_avg_heat: float,
    target_heat: float = _TARGET_HEAT,
    scaling_rate: float = _SCALING_RATE,
) -> float:
    """Compute multiplicative scaling factor from Turrigiano synaptic scaling.

    Implements: delta_w = alpha * w * (r_target - r_actual)
    (Tetzlaff et al. 2011, Frontiers in Computational Neuroscience 5:47, Eq. 3)

    Since delta_w = alpha * w * (r_target - r_actual), the new weight is:
        w_new = w + delta_w = w * (1 + alpha * (r_target - r_actual))

    So the multiplicative factor applied to every weight is:
        factor = 1 + alpha * (r_target - r_actual)

    This is continuous (no dead zone) — Turrigiano scaling is always active,
    and naturally produces no change when r_actual == r_target.

    Args:
        current_avg_heat: Current domain-average heat (r_actual).
        target_heat: Target average heat (r_target).
        scaling_rate: Rate constant alpha. Controls convergence speed.

    Returns:
        Multiplicative scaling factor. Apply to all heats in domain.
    """
    return 1.0 + scaling_rate * (target_heat - current_avg_heat)


def apply_synaptic_scaling(
    heats: list[float],
    scaling_factor: float,
) -> list[float]:
    """Apply multiplicative scaling to a list of heat values.

    Preserves relative ordering (Turrigiano's key finding) and clamps to [0, 1].
    """
    return [max(0.0, min(1.0, h * scaling_factor)) for h in heats]


# ── Metaplasticity (BCM Threshold) ────────────────────────────────────────


def compute_bcm_threshold(
    recent_activity_levels: list[float],
    current_threshold: float = 0.5,
    decay: float = _BCM_THETA_DECAY,
) -> float:
    """Compute the sliding BCM modification threshold.

    BCM theory (Bienenstock, Cooper & Munro 1982):
        theta_M = E[c^2]

    Updated via EMA: theta_new = decay * theta_old + (1 - decay) * E[c^2].
    High activity -> high threshold -> LTP harder (prevents saturation).
    Low activity -> low threshold -> LTP easier (prevents collapse).

    Args:
        recent_activity_levels: Recent activity levels (e.g., heat values).
        current_threshold: Current BCM threshold.
        decay: EMA decay rate.

    Returns:
        Updated BCM threshold.
    """
    if not recent_activity_levels:
        return current_threshold

    avg_squared = sum(a * a for a in recent_activity_levels) / len(
        recent_activity_levels
    )
    return decay * current_threshold + (1 - decay) * avg_squared


def compute_ltp_ltd_modulation(
    memory_heat: float,
    bcm_threshold: float,
) -> tuple[float, float]:
    """Compute LTP/LTD rate modulation using the BCM phi function.

    BCM phi (Bienenstock, Cooper & Munro 1982, Eq. 3):
        phi(c, theta_m) = c * (c - theta_m)

    When c > theta_m: phi > 0 -> LTP.
    When 0 < c < theta_m: phi < 0 -> LTD.

    We convert phi into (ltp_multiplier, ltd_multiplier) pair, both in [0, 2]:
    - phi > 0: ltp_mult = 1 + phi (clamped to 2), ltd_mult = max(0, 1 - phi)
    - phi < 0: ltd_mult = 1 + |phi| (clamped to 2), ltp_mult = max(0, 1 - |phi|)

    Returns:
        (ltp_multiplier, ltd_multiplier). Both in [0, 2].
    """
    phi = memory_heat * (memory_heat - bcm_threshold)

    if phi >= 0:
        ltp_mult = min(2.0, 1.0 + phi)
        ltd_mult = max(0.0, 1.0 - phi)
    else:
        abs_phi = abs(phi)
        ltd_mult = min(2.0, 1.0 + abs_phi)
        ltp_mult = max(0.0, 1.0 - abs_phi)

    return ltp_mult, ltd_mult


# ── Intrinsic Excitability Regulation ─────────────────────────────────────


def compute_excitability_adjustment(
    excitabilities: list[float],
    *,
    target_active_fraction: float = _TARGET_ACTIVE_FRACTION,
    active_threshold: float = 0.5,
) -> float:
    """Compute global excitability adjustment for engram slots.

    Engineering heuristic (no paper source). If too many slots are highly
    excitable, global excitability is dampened. If too few, boost it.
    The gain of 0.1 is hand-tuned for gentle convergence.

    Returns:
        Additive adjustment. Positive = boost, negative = dampen.
    """
    if not excitabilities:
        return 0.0

    active_count = sum(1 for e in excitabilities if e >= active_threshold)
    current_fraction = active_count / len(excitabilities)
    deviation = target_active_fraction - current_fraction
    return deviation * 0.1


def apply_excitability_bounds(
    excitability: float,
    adjustment: float = 0.0,
) -> float:
    """Apply global adjustment and clamp excitability to safe bounds.

    Bounds [0.1, 0.9] are hand-tuned to prevent complete silencing or
    runaway excitation.
    """
    return max(
        _MIN_GLOBAL_EXCITABILITY,
        min(_MAX_GLOBAL_EXCITABILITY, excitability + adjustment),
    )
