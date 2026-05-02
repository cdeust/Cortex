"""Schema engine — matching, accommodation, and evolution of cortical schemas.

Orchestrates the schema lifecycle after formation:
  - Matching: compare new memories against existing schemas
  - Accommodation: update schemas when assimilation fails (Piaget)
  - Revision: detect when a schema needs splitting
  - Predictions: generate top-down expectations for predictive coding

Re-exports formation/merging/serialization from schema_extraction for
backward compatibility.

Theoretical basis (all qualitative — no published equations):
    Tse D et al. (2007) — Experimental demonstration that prior schemas
        accelerate consolidation ~15x in rats. Purely behavioral data;
        no mathematical model or equations are provided.
    van Kesteren MTR et al. (2012) — Conceptual framework: mPFC-mediated
        schema congruency vs MTL-mediated novelty encoding (dual pathway).
        Descriptive model with no computational specification.
    Piaget J (1952) — Assimilation (fit into existing schema) and
        accommodation (modify schema on mismatch) are qualitative
        developmental theory, not a computational model.

Engineering implementation:
    Schema matching uses Jaccard similarity between entity/tag sets —
    an engineering choice to operationalize qualitative "congruency."
    Accommodation uses EMA updates — a standard signal processing
    technique, not derived from any schema paper.
    All thresholds are hand-tuned:
      _HIGH_MATCH=0.7, _MEDIUM_MATCH=0.3, _MAX_VIOLATIONS=10,
      _SCHEMA_EMA_ALPHA=0.1

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.core.schema_extraction import Schema, generate_label
from mcp_server.shared.similarity import jaccard_similarity

# ── Configuration ─────────────────────────────────────────────────────────

_HIGH_MATCH_THRESHOLD = 0.7
_MEDIUM_MATCH_THRESHOLD = 0.3
_MAX_VIOLATIONS_BEFORE_REVISION = 10
_SCHEMA_EMA_ALPHA = 0.1


# ── Schema Matching ───────────────────────────────────────────────────────


def compute_schema_match(
    memory_entities: list[str],
    memory_tags: list[str],
    schema: Schema,
) -> float:
    """Compute how well a new memory matches an existing schema.

    Uses weighted Jaccard overlap between memory entities/tags and schema
    signatures. Entities weighted by their schema frequency.

    Returns:
        Match score [0, 1]. >0.7 = strong match, <0.3 = violation.
    """
    if not schema.entity_signature and not schema.tag_signature:
        return 0.0

    scores: list[float] = []

    if schema.entity_signature:
        entity_score = _compute_entity_match(memory_entities, schema)
        scores.append(entity_score * 0.7)

    if schema.tag_signature:
        tag_jaccard = jaccard_similarity(
            set(memory_tags),
            set(schema.tag_signature.keys()),
        )
        scores.append(tag_jaccard * 0.3)

    return min(1.0, sum(scores))


def _compute_entity_match(
    memory_entities: list[str],
    schema: Schema,
) -> float:
    """Weighted entity overlap between memory and schema signature."""
    memory_entity_set = set(memory_entities)
    schema_entities = set(schema.entity_signature.keys())

    if not memory_entity_set and not schema_entities:
        return 0.0

    overlap = memory_entity_set & schema_entities
    weighted_overlap = sum(schema.entity_signature.get(e, 0.0) for e in overlap)
    total_weight = sum(schema.entity_signature.values())
    return weighted_overlap / max(total_weight, 1e-10)


def classify_schema_match(match_score: float) -> str:
    """Classify a schema match score into a consolidation pathway.

    Returns:
        "assimilate" — fast consolidation (schema-consistent)
        "normal" — standard hippocampal consolidation
        "accommodate" — slow consolidation + schema update signal
    """
    if match_score >= _HIGH_MATCH_THRESHOLD:
        return "assimilate"
    if match_score >= _MEDIUM_MATCH_THRESHOLD:
        return "normal"
    return "accommodate"


def find_best_matching_schema(
    memory_entities: list[str],
    memory_tags: list[str],
    schemas: list[Schema],
) -> tuple[Schema | None, float]:
    """Find the schema that best matches a new memory.

    Returns:
        (best_schema, match_score). None if no schema scores above 0.1.
    """
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.SCHEMA_ENGINE):
        # No-op: never match a schema.
        return None, 0.0

    best_schema: Schema | None = None
    best_score = 0.0

    for schema in schemas:
        score = compute_schema_match(memory_entities, memory_tags, schema)
        if score > best_score:
            best_score = score
            best_schema = schema

    if best_score < 0.1:
        return None, 0.0
    return best_schema, best_score


# ── Schema Accommodation (Update) ────────────────────────────────────────


def accommodate_schema(
    schema: Schema,
    new_entities: list[str],
    new_tags: list[str],
    *,
    alpha: float = _SCHEMA_EMA_ALPHA,
) -> Schema:
    """Update a schema via Piaget accommodation using EMA.

    Gradually shifts the schema's expectations toward new data
    without catastrophic overwriting.

    Returns:
        Updated schema (new object, original not mutated).
    """
    updated_entities = _ema_update_signature(
        schema.entity_signature,
        new_entities,
        alpha,
    )
    updated_tags = _ema_update_signature(
        schema.tag_signature,
        new_tags,
        alpha,
    )

    return Schema(
        schema_id=schema.schema_id,
        domain=schema.domain,
        label=generate_label(updated_entities, updated_tags),
        entity_signature=updated_entities,
        relationship_types=schema.relationship_types,
        tag_signature=updated_tags,
        consistency_threshold=schema.consistency_threshold,
        formation_count=schema.formation_count,
        assimilation_count=schema.assimilation_count,
        violation_count=schema.violation_count + 1,
        last_updated_hours=0.0,
    )


def _ema_update_signature(
    current: dict[str, float],
    observed: list[str],
    alpha: float,
) -> dict[str, float]:
    """EMA update for a frequency signature dict.

    - Observed items: EMA toward 1.0, or introduced at alpha.
    - Unobserved items: decay by alpha * 0.5, pruned below 0.05.
    """
    updated = dict(current)
    observed_set = set(observed)

    for item in observed:
        if item in updated:
            updated[item] = (1 - alpha) * updated[item] + alpha * 1.0
        else:
            updated[item] = alpha

    for item in list(updated):
        if item not in observed_set:
            updated[item] *= 1 - alpha * 0.5
            if updated[item] < 0.05:
                del updated[item]

    return updated


# ── Schema Revision ──────────────────────────────────────────────────────


def should_revise_schema(schema: Schema) -> bool:
    """Check if a schema has accumulated enough violations to need revision."""
    total_usage = schema.formation_count + schema.assimilation_count
    if total_usage == 0:
        return False

    violation_ratio = schema.violation_count / max(total_usage, 1)

    return (
        schema.violation_count >= _MAX_VIOLATIONS_BEFORE_REVISION
        or violation_ratio > 0.4
    )


# ── Schema Predictions (for Predictive Coding) ───────────────────────────


def generate_predictions(schema: Schema) -> dict[str, float]:
    """Generate top-down predictions from a schema.

    These are the "expected entities" that the hierarchical predictive
    coding system (Level 2) uses to compute prediction errors.
    """
    return dict(schema.entity_signature)


def compute_prediction_error(
    predictions: dict[str, float],
    observed_entities: list[str],
) -> dict[str, float]:
    """Compute signed prediction errors between predictions and observations.

    Positive error: entity was predicted but not observed (missing).
    Negative error: entity was observed but not predicted (novel).
    """
    observed_set = set(observed_entities)
    errors: dict[str, float] = {}

    for entity, prob in predictions.items():
        if entity not in observed_set:
            errors[entity] = prob

    for entity in observed_entities:
        if entity not in predictions:
            errors[entity] = -0.5

    return errors


def compute_schema_free_energy(prediction_errors: dict[str, float]) -> float:
    """Compute schema-level free energy from prediction errors.

    Free energy = sum of squared prediction errors.
    High free energy signals the schema needs updating.
    """
    if not prediction_errors:
        return 0.0
    return sum(e * e for e in prediction_errors.values())
