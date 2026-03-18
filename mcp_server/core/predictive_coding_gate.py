"""Predictive coding gate -- precision management, neuromodulation, gate decisions.

Manages precision-weighted prediction errors (Feldman & Friston 2010),
neuromodulatory gain control (NE/ACh), calibration tracking, and
gate decisions for both flat and hierarchical pipelines.

References:
    Feldman H, Friston K (2010) Attention, uncertainty, and free-energy.
        Front Hum Neurosci 4:215
    Yu AJ, Dayan P (2005) Uncertainty, neuromodulation, and attention.
        Neuron 46:681-692
    Kanai R et al. (2015) Cerebral hierarchies: predictive processing,
        precision, and the pulvinar. Phil Trans R Soc B 370:20140169

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from mcp_server.core.predictive_coding_signals import (
    HierarchicalPrediction,
)


# -- Precision state -----------------------------------------------------------


@dataclass
class PrecisionState:
    """Domain-level precision tracking for prediction error weighting.

    Precision = inverse variance of past prediction errors. High precision means
    we're confident in our predictions, so violations are more surprising.

    NE modulates precision gain: high arousal amplifies all precision weights.
    ACh modulates the ratio between bottom-up (L0/L1) and top-down (L2) precision.
    """

    domain: str = ""
    level_precisions: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    prediction_history: int = 0
    calibration_hits: int = 0
    calibration_total: int = 0
    precision_ema_alpha: float = 0.1


# -- Precision update ----------------------------------------------------------


def update_precision(
    current_precision: float,
    prediction_error: float,
    *,
    learning_rate: float = 0.1,
    min_precision: float = 0.1,
    max_precision: float = 5.0,
) -> float:
    """Update precision estimate via inverse variance tracking.

    Precision increases when prediction errors are small (good predictions)
    and decreases when they're large (bad predictions).
    """
    current_var = 1.0 / max(current_precision, min_precision)
    new_var = (1 - learning_rate) * current_var + learning_rate * (prediction_error**2)
    new_precision = 1.0 / max(new_var, 1e-10)
    return max(min_precision, min(max_precision, new_precision))


# -- Neuromodulatory gain control ----------------------------------------------


def neuromodulate_precisions(
    level_precisions: list[float],
    ne_level: float = 1.0,
    ach_level: float = 0.5,
) -> list[float]:
    """Apply neuromodulatory gain to per-level precisions.

    NE: global gain control (high NE = amplify all precisions).
    ACh: bottom-up vs top-down ratio (high ACh = boost L0/L1, dampen L2).
    """
    ne_gain = 0.5 + 0.5 * ne_level
    ach_norm = max(0.0, min(1.0, (ach_level - 0.3) / 0.7))
    bu_boost = 0.7 + 0.6 * ach_norm
    td_boost = 1.3 - 0.6 * ach_norm

    modulated = [
        level_precisions[0] * ne_gain * bu_boost,
        level_precisions[1] * ne_gain * bu_boost,
        level_precisions[2] * ne_gain * td_boost,
    ]
    return [max(0.1, min(10.0, p)) for p in modulated]


# -- Precision state lifecycle -------------------------------------------------


def update_precision_state(
    state: PrecisionState,
    level_errors: list[float],
) -> PrecisionState:
    """Update domain precision state after observing prediction errors."""
    alpha = state.precision_ema_alpha
    new_precisions = []

    for current_prec, error_fe in zip(state.level_precisions, level_errors):
        current_var = 1.0 / max(current_prec, 0.1)
        new_var = (1 - alpha) * current_var + alpha * error_fe
        new_prec = 1.0 / max(new_var, 0.01)
        new_precisions.append(max(0.1, min(10.0, new_prec)))

    return PrecisionState(
        domain=state.domain,
        level_precisions=new_precisions,
        prediction_history=state.prediction_history + 1,
        calibration_hits=state.calibration_hits,
        calibration_total=state.calibration_total,
        precision_ema_alpha=alpha,
    )


def precision_to_confidence(level_precisions: list[float]) -> float:
    """Convert precision estimates to a confidence score [0, 1].

    Sigmoid mapping: precision=1.0 -> ~0.5, precision=3.0 -> ~0.85.
    """
    avg_prec = (
        sum(level_precisions) / len(level_precisions) if level_precisions else 1.0
    )
    return 1.0 / (1.0 + math.exp(-1.5 * (avg_prec - 1.5)))


# -- Calibration tracking -----------------------------------------------------


def check_calibration(
    state: PrecisionState,
    predicted_confidence: float,
    was_useful: bool,
    threshold: float = 0.6,
) -> PrecisionState:
    """Track metamemory calibration: are confident predictions actually useful?"""
    new_total = state.calibration_total + 1
    new_hits = state.calibration_hits

    if predicted_confidence >= threshold and was_useful:
        new_hits += 1

    return PrecisionState(
        domain=state.domain,
        level_precisions=state.level_precisions,
        prediction_history=state.prediction_history,
        calibration_hits=new_hits,
        calibration_total=new_total,
        precision_ema_alpha=state.precision_ema_alpha,
    )


def calibration_score(state: PrecisionState) -> float:
    """Compute calibration accuracy. Returns 0.5 if insufficient data."""
    if state.calibration_total < 5:
        return 0.5
    return state.calibration_hits / state.calibration_total


# -- Gate decisions ------------------------------------------------------------

_DEFAULT_THRESHOLD = 0.15


def gate_decision(
    novelty_score: float,
    threshold: float = 0.4,
    *,
    bypass: bool = False,
) -> tuple[bool, str]:
    """Backward-compatible flat gate decision."""
    if bypass:
        return True, "bypass"
    if novelty_score >= threshold:
        return True, "high_novelty"
    return (
        False,
        f"below_threshold (novelty={novelty_score:.3f}, threshold={threshold})",
    )


def hierarchical_gate_decision(
    prediction: HierarchicalPrediction,
    threshold: float = _DEFAULT_THRESHOLD,
    *,
    bypass: bool = False,
) -> tuple[bool, str]:
    """Gate decision using hierarchical free energy."""
    if bypass:
        return True, "bypass"

    fe = prediction.total_free_energy

    if fe >= threshold:
        dominant_level = max(range(3), key=lambda i: prediction.levels[i].free_energy)
        level_names = ["sensory", "entity", "schema"]
        return (
            True,
            f"high_free_energy (FE={fe:.3f}, dominant={level_names[dominant_level]})",
        )

    return False, f"low_free_energy (FE={fe:.3f}, threshold={threshold})"


# -- Observability -------------------------------------------------------------


def _top_errors(errors: dict[str, float], n: int) -> dict[str, float]:
    """Get the N largest absolute prediction errors."""
    sorted_errors = sorted(errors.items(), key=lambda x: abs(x[1]), reverse=True)
    return {k: round(v, 4) for k, v in sorted_errors[:n]}


def describe_hierarchical_signals(
    prediction: HierarchicalPrediction,
) -> dict[str, Any]:
    """Structured description of hierarchical prediction for observability."""
    return {
        "total_free_energy": prediction.total_free_energy,
        "novelty_score": prediction.novelty_score,
        "gate_open": prediction.gate_open,
        "gate_reason": prediction.gate_reason,
        "level_0_sensory": {
            "free_energy": round(prediction.levels[0].free_energy, 4),
            "top_errors": _top_errors(prediction.levels[0].prediction_errors, 3),
        },
        "level_1_entity": {
            "free_energy": round(prediction.levels[1].free_energy, 4),
            "top_errors": _top_errors(prediction.levels[1].prediction_errors, 3),
        },
        "level_2_schema": {
            "free_energy": round(prediction.levels[2].free_energy, 4),
            "top_errors": _top_errors(prediction.levels[2].prediction_errors, 3),
        },
    }
