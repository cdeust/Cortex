"""Predictive coding signal computation -- sensory, entity, schema errors.

Level 0 (Sensory): Raw content features (length, structure, code blocks, file refs).
Level 1 (Entity): Entity and relationship pattern novelty.
Level 2 (Schema): Domain-level regularity matching.

Also re-exports flat 4-signal novelty functions used by the remember handler
and write_gate (embedding, entity, temporal, structural).

References:
    Friston K (2005) A theory of cortical responses.
        Phil Trans R Soc B 360:815-836
    Bastos AM et al. (2012) Canonical microcircuits for predictive coding.
        Neuron 76:695-711

Pure business logic -- no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_server.core.predictive_coding_flat import (
    _CODE_BLOCK_RE,
    _FILE_PATH_RE,
    _HEADING_RE,
    _LIST_RE,
    _URL_RE,
)

# -- Data classes -------------------------------------------------------------


@dataclass
class PredictionLevel:
    """State of one level in the predictive hierarchy."""

    level: int = 0
    predictions: dict[str, float] = field(default_factory=dict)
    precisions: dict[str, float] = field(default_factory=dict)
    prediction_errors: dict[str, float] = field(default_factory=dict)
    free_energy: float = 0.0


@dataclass
class HierarchicalPrediction:
    """Full hierarchical prediction state across all levels."""

    levels: list[PredictionLevel] = field(
        default_factory=lambda: [
            PredictionLevel(level=0),
            PredictionLevel(level=1),
            PredictionLevel(level=2),
        ]
    )
    total_free_energy: float = 0.0
    novelty_score: float = 0.0
    gate_open: bool = False
    gate_reason: str = ""


# -- Level 0: Sensory feature extraction --------------------------------------


def _extract_sensory_features(content: str) -> dict[str, float]:
    """Extract Level 0 (sensory) features from content."""
    n = max(len(content), 1)
    return {
        "length": min(n / 2000.0, 1.0),
        "code_density": min(len(_CODE_BLOCK_RE.findall(content)) / 5.0, 1.0),
        "file_ref_density": min(len(_FILE_PATH_RE.findall(content)) / 5.0, 1.0),
        "url_density": min(len(_URL_RE.findall(content)) / 3.0, 1.0),
        "heading_density": min(len(_HEADING_RE.findall(content)) / 5.0, 1.0),
        "list_density": min(len(_LIST_RE.findall(content)) / 10.0, 1.0),
    }


_DEFAULT_SENSORY_PREDICTIONS = {
    "length": 0.3,
    "code_density": 0.2,
    "file_ref_density": 0.1,
    "url_density": 0.05,
    "heading_density": 0.1,
    "list_density": 0.1,
}


def compute_sensory_prediction(
    recent_memories_features: list[dict[str, float]],
) -> tuple[dict[str, float], dict[str, float]]:
    """Generate Level 0 predictions from recent memory statistics."""
    if not recent_memories_features:
        default_prec = {k: 0.5 for k in _DEFAULT_SENSORY_PREDICTIONS}
        return dict(_DEFAULT_SENSORY_PREDICTIONS), default_prec

    features = list(recent_memories_features[0].keys())
    predictions: dict[str, float] = {}
    precisions: dict[str, float] = {}

    for feat in features:
        values = [m.get(feat, 0.0) for m in recent_memories_features]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)
        predictions[feat] = mean
        precisions[feat] = max(0.1, min(5.0, 1.0 / max(variance, 0.01)))

    return predictions, precisions


def compute_sensory_errors(
    content: str,
    predictions: dict[str, float],
    precisions: dict[str, float],
) -> PredictionLevel:
    """Compute Level 0 prediction errors for new content."""
    observations = _extract_sensory_features(content)
    errors: dict[str, float] = {}
    free_energy = 0.0

    for feat, pred in predictions.items():
        obs = observations.get(feat, 0.0)
        error = obs - pred
        errors[feat] = error
        precision = precisions.get(feat, 1.0)
        free_energy += precision * (error**2)

    return PredictionLevel(
        level=0,
        predictions=predictions,
        precisions=precisions,
        prediction_errors=errors,
        free_energy=free_energy,
    )


# -- Level 1: Entity prediction -----------------------------------------------


def _compute_entity_errors_with_schema(
    new_set: set[str],
    new_entity_names: list[str],
    predictions: dict[str, float],
    precisions: dict[str, float],
) -> tuple[dict[str, float], float]:
    """Compute entity errors when schema predictions are available."""
    errors: dict[str, float] = {}
    free_energy = 0.0

    for entity, prob in predictions.items():
        prec = precisions.get(entity, 1.0)
        error = 0.0 if entity in new_set else prob
        errors[entity] = error
        free_energy += prec * (error**2)

    for entity in new_entity_names:
        if entity not in predictions:
            errors[entity] = -0.5
            free_energy += 0.5 * 0.25

    return errors, free_energy


def compute_entity_errors(
    new_entity_names: list[str],
    known_entity_names: set[str],
    entity_predictions: dict[str, float] | None = None,
    entity_precisions: dict[str, float] | None = None,
) -> PredictionLevel:
    """Compute Level 1 (entity) prediction errors."""
    predictions = entity_predictions or {}
    precisions = entity_precisions or {}
    new_set = set(new_entity_names)

    if predictions:
        errors, free_energy = _compute_entity_errors_with_schema(
            new_set,
            new_entity_names,
            predictions,
            precisions,
        )
    elif not new_entity_names:
        return PredictionLevel(level=1, free_energy=0.0)
    else:
        novel = sum(1 for e in new_entity_names if e not in known_entity_names)
        novelty_ratio = novel / len(new_entity_names)
        errors = {"entity_novelty_ratio": novelty_ratio}
        free_energy = novelty_ratio**2

    return PredictionLevel(
        level=1,
        predictions=predictions,
        precisions=precisions,
        prediction_errors=errors,
        free_energy=free_energy,
    )


# -- Level 2: Schema prediction -----------------------------------------------


def compute_schema_errors(
    schema_match_score: float,
    schema_free_energy: float,
    domain_familiarity: float = 0.5,
) -> PredictionLevel:
    """Compute Level 2 (schema/domain) prediction errors."""
    schema_error = 1.0 - schema_match_score
    domain_precision = 0.5 + domain_familiarity * 2.0
    total_fe = domain_precision * (schema_error**2) + schema_free_energy * 0.3

    return PredictionLevel(
        level=2,
        predictions={
            "schema_match": schema_match_score,
            "domain_familiarity": domain_familiarity,
        },
        precisions={"schema_match": domain_precision},
        prediction_errors={"schema_mismatch": schema_error},
        free_energy=total_fe,
    )
