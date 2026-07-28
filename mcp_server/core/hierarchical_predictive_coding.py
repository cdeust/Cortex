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
    Feldman H, Friston K (2010) Attention, uncertainty, and free-energy.
        Front Hum Neurosci 4:215
    Yu AJ, Dayan P (2005) Uncertainty, neuromodulation, and attention.
        Neuron 46:681-692

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math

from mcp_server.core.predictive_coding_flat import (
    compute_embedding_novelty,
    compute_entity_novelty,
    compute_structural_novelty,
    compute_temporal_novelty,
)
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
from mcp_server.core.forward_model import prediction_error, scalar_of
from mcp_server.core.predictive_coding_signals import extract_sensory_features
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

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


# -- Precision-weighted level combination --------------------------------------
#
# Friston's free energy is the precision-weighted sum of squared prediction
# errors across the hierarchy: F = Sum_i pi_i * eps_i^2 (Friston 2005;
# Friston & Kiebel 2009). Cross-level contributions are weighted by PRECISION
# (inverse variance, encoded as the synaptic gain on error units --
# Feldman & Friston 2010), NOT by a fixed prior. Precision is neuromodulated
# by NE (global gain) and ACh (bottom-up vs top-down ratio -- Yu & Dayan 2005)
# inside ``neuromodulate_precisions``. There are therefore deliberately no free
# cross-level weight constants in this module: the combination is derived
# entirely from the precision values. (Earlier revisions used a fixed prior
# [0.30, 0.35, 0.35] plus a duplicate ACh-weight transform; both were ungrounded
# borrowings of the Friston label and have been removed in favour of the
# precision-derived sum.)

# source: PrecisionState default (predictive_coding_gate.py) -- unit precision
# (variance 1.0) for a domain with no observed prediction-error history.
_DEFAULT_LEVEL_PRECISIONS = [1.0, 1.0, 1.0]  # Sensory, Entity, Schema


def _level_precisions(
    precision_state: PrecisionState | None,
    ne_level: float,
    ach_level: float,
) -> list[float]:
    """Cross-level precisions pi_i, neuromodulated by NE (gain) and ACh (ratio).

    Friston: each level's contribution to total free energy is scaled by its
    precision (inverse variance), not a fixed prior. Falls back to unit
    precision when no domain precision-error history exists.
    """
    base = (
        precision_state.level_precisions
        if precision_state is not None
        else list(_DEFAULT_LEVEL_PRECISIONS)
    )
    return neuromodulate_precisions(base, ne_level, ach_level)


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
    level_precisions: list[float],
) -> tuple[float, float]:
    """Combine per-level free energies into total free energy + novelty score.

    Total free energy is the precision-weighted sum F = Sum_i pi_i * F_i
    (Friston 2005 eq. 7; Friston & Kiebel 2009) -- additive across levels, each
    weighted by its cross-level precision pi_i. No fixed cross-level prior is
    used; NE amplifies all precisions and ACh shifts the bottom-up/top-down
    ratio via ``neuromodulate_precisions``.
    """
    # strict=True: exactly one precision per level -- a length mismatch would
    # silently drop a level's free energy from the total, corrupting the gate.
    total_fe = sum(
        prec * level.free_energy
        for prec, level in zip(level_precisions, levels, strict=True)
    )
    # source: engineering (logistic squash of unbounded free energy -> [0,1] so
    # the gate sees a comparable novelty score); NOT from Friston. Steepness 3.0
    # and midpoint 0.5 are uncalibrated defaults -- calibration pending
    # (benchmarks/gate_precision/run_benchmark.py). The additive precision-
    # weighted free-energy aggregation above is the Fristonian part; this
    # mapping is a presentation transform only.
    novelty = 1.0 / (1.0 + math.exp(-3.0 * (total_fe - 0.5)))
    return total_fe, max(0.0, min(1.0, novelty))


def _forward_model_error(
    content: str,
    recent_memories_features: list[dict[str, float]],
) -> float:
    """B3 cerebellar forward-model corrective-error term for the novelty score.

    Treats the mean sensory-feature activation of the recent memories as a
    scalar *trajectory*, builds the one-step forward model over it
    (forward_model.run_forward_model), and returns |residual| of the new
    content's own mean activation against that model's one-step prediction — a
    non-negative "the dynamics did not predict this step" surplus. Zero when
    there is no history or the step fell within the model's deadband.

    Distinct from the Level-0 sensory novelty (which scores the new item against
    the per-feature mean/variance of recent items): this scores the new item
    against a *corrected running estimate of the trajectory*, the genuinely-new
    B3 contribution (see forward_model.py honesty note). Kept small and additive.
    """

    if not recent_memories_features:
        return 0.0
    trajectory = [scalar_of(f) for f in recent_memories_features]
    actual = scalar_of(extract_sensory_features(content))
    return abs(prediction_error(trajectory, actual))


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
    include_forward_model: bool = False,
) -> HierarchicalPrediction:
    """Run the full hierarchical predictive coding pipeline.

    ``include_forward_model`` (B3, default False → behaviour byte-identical to
    the pre-B3 scorer) opts in to adding a small cerebellar forward-model
    corrective-error term to total free energy before the novelty sigmoid. Even
    when opted in, the term is suppressed to 0.0 under
    ``CORTEX_ABLATE_FORWARD_MODEL=1`` (Mechanism.FORWARD_MODEL), so the ablation
    condition reproduces the include_forward_model=False score exactly.
    """
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

    level_precisions = _level_precisions(precision_state, ne_level, ach_level)
    total_fe, novelty = _aggregate_novelty(levels, level_precisions)

    fm_error = 0.0
    if include_forward_model:
        if not is_mechanism_disabled(Mechanism.FORWARD_MODEL):
            fm_error = _forward_model_error(content, recent_memories_features)
            if fm_error > 0.0:
                total_fe = total_fe + fm_error
                novelty = 1.0 / (1.0 + math.exp(-3.0 * (total_fe - 0.5)))
                novelty = max(0.0, min(1.0, novelty))

    return HierarchicalPrediction(
        levels=levels,
        total_free_energy=round(total_fe, 6),
        novelty_score=round(novelty, 4),
    )
