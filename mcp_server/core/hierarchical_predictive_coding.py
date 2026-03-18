"""Hierarchical predictive coding -- Fristonian multi-level novelty gate.

Orchestrates the 3-level predictive hierarchy (sensory, entity, schema)
and computes combined free energy as the novelty signal for the write gate.

This module composes signals from predictive_coding_signals and gate logic
from predictive_coding_gate. All public names are re-exported here for
backward compatibility.

References:
    Friston K (2005) A theory of cortical responses.
        Phil Trans R Soc B 360:815-836
    Friston K, Kiebel S (2009) Predictive coding under the free-energy
        principle. Phil Trans R Soc B 364:1211-1221

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math

from mcp_server.core.predictive_coding_gate import (
    PrecisionState,
    neuromodulate_precisions,
)
from mcp_server.core.predictive_coding_signals import (
    HierarchicalPrediction,
    PredictionLevel,
    compute_entity_errors,
    compute_schema_errors,
    compute_sensory_errors,
    compute_sensory_prediction,
)
from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty,
    compute_entity_novelty,
    compute_structural_novelty,
    compute_temporal_novelty,
)


__all__ = [
    "PredictionLevel",
    "HierarchicalPrediction",
    "PrecisionState",
    "compute_sensory_prediction",
    "compute_sensory_errors",
    "compute_entity_errors",
    "compute_schema_errors",
    "compute_hierarchical_novelty",
    "compute_embedding_novelty",
    "compute_entity_novelty",
    "compute_temporal_novelty",
    "compute_structural_novelty",
    "neuromodulate_precisions",
]


# -- Level weights for hierarchical combination --------------------------------

_LEVEL_WEIGHTS = [0.30, 0.35, 0.35]  # Sensory, Entity, Schema


# -- ACh-modulated level weights -----------------------------------------------


def _compute_ach_weights(ach_level: float) -> tuple[float, float, float]:
    """Compute ACh-modulated level weights, normalized to sum to 1.

    High ACh (encoding): boost L0/L1 (bottom-up), reduce L2.
    Low ACh (retrieval): boost L2 (top-down), reduce L0/L1.
    """
    ach_norm = (ach_level - 0.3) / 0.7
    weight_0 = _LEVEL_WEIGHTS[0] * (0.7 + 0.6 * ach_norm)
    weight_1 = _LEVEL_WEIGHTS[1] * (0.7 + 0.6 * ach_norm)
    weight_2 = _LEVEL_WEIGHTS[2] * (1.3 - 0.6 * ach_norm)
    total = weight_0 + weight_1 + weight_2

    if total > 0:
        weight_0 /= total
        weight_1 /= total
        weight_2 /= total

    return weight_0, weight_1, weight_2


def _apply_precision_modulation(
    levels: list[PredictionLevel],
    precision_state: PrecisionState,
    ne_level: float,
    ach_level: float,
) -> None:
    """Apply NE/ACh precision gain to each level's free energy in-place."""
    modulated_prec = neuromodulate_precisions(
        precision_state.level_precisions,
        ne_level,
        ach_level,
    )
    for i, level in enumerate(levels):
        level.free_energy *= modulated_prec[i]


# -- Main orchestrator ---------------------------------------------------------


def _compute_prediction_levels(
    content: str,
    new_entity_names: list[str],
    known_entity_names: set[str],
    recent_memories_features: list[dict[str, float]],
    schema_match_score: float,
    schema_free_energy: float,
    schema_predictions: dict[str, float] | None,
    schema_precisions: dict[str, float] | None,
    domain_familiarity: float,
) -> list[PredictionLevel]:
    """Compute prediction errors at all three hierarchical levels."""
    sensory_pred, sensory_prec = compute_sensory_prediction(recent_memories_features)
    level_0 = compute_sensory_errors(content, sensory_pred, sensory_prec)
    level_1 = compute_entity_errors(
        new_entity_names,
        known_entity_names,
        schema_predictions,
        schema_precisions,
    )
    level_2 = compute_schema_errors(
        schema_match_score,
        schema_free_energy,
        domain_familiarity,
    )
    return [level_0, level_1, level_2]


def _aggregate_novelty(
    levels: list[PredictionLevel],
    ach_level: float,
) -> tuple[float, float]:
    """Aggregate level free energies into total free energy and novelty score."""
    w0, w1, w2 = _compute_ach_weights(ach_level)
    total_fe = (
        w0 * levels[0].free_energy
        + w1 * levels[1].free_energy
        + w2 * levels[2].free_energy
    )
    novelty = 1.0 / (1.0 + math.exp(-3.0 * (total_fe - 0.5)))
    return total_fe, max(0.0, min(1.0, novelty))


def compute_hierarchical_novelty(
    content: str,
    new_entity_names: list[str],
    known_entity_names: set[str],
    recent_memories_features: list[dict[str, float]],
    *,
    schema_match_score: float = 0.0,
    schema_free_energy: float = 0.0,
    schema_predictions: dict[str, float] | None = None,
    schema_precisions: dict[str, float] | None = None,
    domain_familiarity: float = 0.5,
    ach_level: float = 0.5,
    ne_level: float = 1.0,
    precision_state: PrecisionState | None = None,
) -> HierarchicalPrediction:
    """Run the full hierarchical predictive coding pipeline."""
    levels = _compute_prediction_levels(
        content,
        new_entity_names,
        known_entity_names,
        recent_memories_features,
        schema_match_score,
        schema_free_energy,
        schema_predictions,
        schema_precisions,
        domain_familiarity,
    )

    if precision_state is not None:
        _apply_precision_modulation(levels, precision_state, ne_level, ach_level)

    total_fe, novelty = _aggregate_novelty(levels, ach_level)

    return HierarchicalPrediction(
        levels=levels,
        total_free_energy=round(total_fe, 6),
        novelty_score=round(novelty, 4),
    )
