"""Schema extraction — formation from clusters and merging of schemas.

Handles the creation side of the schema lifecycle:
  1. Formation: cluster of memories -> Schema via entity/tag frequency analysis
  2. Merging: two similar schemas -> single unified Schema

Theoretical basis (all qualitative — no published equations):
    Tse D et al. (2007) — Demonstrates schema-accelerated consolidation
        in rats (~15x faster). No computational model provided.
    Gilboa A, Marlatte H (2017) — Reviews neurobiology of schemas:
        schemas as networks of neocortical traces, schema formation via
        statistical regularity extraction. Conceptual framework only.

Engineering implementation:
    Schema formation extracts entity/tag frequencies from memory clusters
    using simple counting and threshold filtering. Merging uses Jaccard
    similarity — standard set overlap, not derived from any schema paper.
    All thresholds are hand-tuned:
      _MIN_FORMATION_COUNT=5, _ENTITY_FREQUENCY_THRESHOLD=0.4,
      _HIGH_MATCH_THRESHOLD=0.7, _SCHEMA_MERGE_THRESHOLD=0.6,
      _SCHEMA_EMA_ALPHA=0.1, _RELATIONSHIP_FREQUENCY_THRESHOLD=0.3

Pure business logic — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mcp_server.shared.similarity import jaccard_similarity

# ── Configuration ─────────────────────────────────────────────────────────

_MIN_FORMATION_COUNT = 5
_ENTITY_FREQUENCY_THRESHOLD = 0.4
_HIGH_MATCH_THRESHOLD = 0.7
_SCHEMA_MERGE_THRESHOLD = 0.6
_SCHEMA_EMA_ALPHA = 0.1
_RELATIONSHIP_FREQUENCY_THRESHOLD = 0.3


# ── Schema Data Model ─────────────────────────────────────────────────────


@dataclass
class Schema:
    """An abstracted knowledge structure representing domain regularities.

    Attributes:
        schema_id: Unique identifier.
        domain: Domain this schema belongs to.
        label: Human-readable description.
        entity_signature: Expected entities with their frequency weights.
        relationship_types: Expected relationship patterns.
        tag_signature: Expected tags with frequencies.
        consistency_threshold: How flexible this schema is (adapts over time).
        formation_count: Number of memories that built this schema.
        assimilation_count: Memories that matched and used this schema.
        violation_count: Memories that strongly violated expectations.
        last_updated_hours: Hours since last schema update.
    """

    schema_id: str = ""
    domain: str = ""
    label: str = ""
    entity_signature: dict[str, float] = field(default_factory=dict)
    relationship_types: list[tuple[str, str, str]] = field(default_factory=list)
    tag_signature: dict[str, float] = field(default_factory=dict)
    consistency_threshold: float = _HIGH_MATCH_THRESHOLD
    formation_count: int = 0
    assimilation_count: int = 0
    violation_count: int = 0
    last_updated_hours: float = 0.0


# ── Schema Formation ─────────────────────────────────────────────────────


def extract_schema_from_cluster(
    cluster_memories: list[dict],
    domain: str = "",
    schema_id: str = "",
    *,
    entity_threshold: float = _ENTITY_FREQUENCY_THRESHOLD,
    min_memories: int = _MIN_FORMATION_COUNT,
) -> Schema | None:
    """Form a schema from a cluster of related memories.

    Extracts recurring entities, tags, and relationship patterns that appear
    across multiple memories in the cluster.

    Returns:
        Schema if formation criteria met, None otherwise.
    """
    if len(cluster_memories) < min_memories:
        return None

    n = len(cluster_memories)
    entity_signature = _extract_entity_signature(cluster_memories, n, entity_threshold)
    tag_signature = _extract_tag_signature(cluster_memories, n, entity_threshold)
    frequent_patterns = _extract_relationship_patterns(cluster_memories, n)

    if not entity_signature and not tag_signature:
        return None

    return Schema(
        schema_id=schema_id,
        domain=domain,
        label=generate_label(entity_signature, tag_signature),
        entity_signature=entity_signature,
        relationship_types=frequent_patterns,
        tag_signature=tag_signature,
        formation_count=n,
    )


def _extract_entity_signature(
    memories: list[dict],
    n: int,
    threshold: float,
) -> dict[str, float]:
    """Count entity frequencies and filter to those above threshold."""
    entity_counts: dict[str, int] = {}
    for mem in memories:
        seen: set[str] = set()
        for ent in mem.get("entities", []):
            name = ent if isinstance(ent, str) else ent.get("name", "")
            if name and name not in seen:
                entity_counts[name] = entity_counts.get(name, 0) + 1
                seen.add(name)

    return {
        name: count / n
        for name, count in entity_counts.items()
        if count / n >= threshold
    }


def _extract_tag_signature(
    memories: list[dict],
    n: int,
    threshold: float,
) -> dict[str, float]:
    """Count tag frequencies and filter to those above threshold."""
    tag_counts: dict[str, int] = {}
    for mem in memories:
        for tag in mem.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        tag: count / n for tag, count in tag_counts.items() if count / n >= threshold
    }


def _extract_relationship_patterns(
    memories: list[dict],
    n: int,
) -> list[tuple[str, str, str]]:
    """Extract relationship patterns appearing in >= 30% of memories."""
    rel_patterns: dict[tuple[str, str, str], int] = {}
    for mem in memories:
        for rel in mem.get("relationships", []):
            if isinstance(rel, dict):
                pattern = (
                    rel.get("source_type", ""),
                    rel.get("relationship_type", ""),
                    rel.get("target_type", ""),
                )
                if all(pattern):
                    rel_patterns[pattern] = rel_patterns.get(pattern, 0) + 1

    return [
        pattern
        for pattern, count in rel_patterns.items()
        if count / n >= _RELATIONSHIP_FREQUENCY_THRESHOLD
    ]


def generate_label(
    entity_sig: dict[str, float],
    tag_sig: dict[str, float],
) -> str:
    """Generate a human-readable label from schema signatures."""
    top_entities = sorted(entity_sig.items(), key=lambda x: x[1], reverse=True)[:3]
    top_tags = sorted(tag_sig.items(), key=lambda x: x[1], reverse=True)[:2]

    parts = [name for name, _ in top_entities]
    if top_tags:
        parts.append(f"[{', '.join(t for t, _ in top_tags)}]")
    return " + ".join(parts) if parts else "unnamed_schema"


# ── Schema Merging ────────────────────────────────────────────────────────


def should_merge_schemas(schema_a: Schema, schema_b: Schema) -> bool:
    """Check if two schemas are similar enough to merge."""
    entities_a = set(schema_a.entity_signature.keys())
    entities_b = set(schema_b.entity_signature.keys())
    return jaccard_similarity(entities_a, entities_b) >= _SCHEMA_MERGE_THRESHOLD


def _compute_merge_weights(
    schema_a: Schema, schema_b: Schema
) -> tuple[float, float, int]:
    """Compute formation-count-proportional weights for merging."""
    total = schema_a.formation_count + schema_b.formation_count
    if total == 0:
        total = 1
    return schema_a.formation_count / total, schema_b.formation_count / total, total


def merge_schemas(
    schema_a: Schema,
    schema_b: Schema,
    merged_id: str = "",
) -> Schema:
    """Merge two similar schemas into one via weighted average.

    Weights are proportional to formation count.
    """
    w_a, w_b, total = _compute_merge_weights(schema_a, schema_b)

    merged_entities = _weighted_merge_dicts(
        schema_a.entity_signature, schema_b.entity_signature, w_a, w_b
    )
    merged_tags = _weighted_merge_dicts(
        schema_a.tag_signature, schema_b.tag_signature, w_a, w_b
    )
    all_rels = list(set(schema_a.relationship_types) | set(schema_b.relationship_types))

    return Schema(
        schema_id=merged_id or f"merged_{schema_a.schema_id}_{schema_b.schema_id}",
        domain=schema_a.domain or schema_b.domain,
        label=generate_label(merged_entities, merged_tags),
        entity_signature=merged_entities,
        relationship_types=all_rels,
        tag_signature=merged_tags,
        consistency_threshold=min(
            schema_a.consistency_threshold, schema_b.consistency_threshold
        ),
        formation_count=total,
        assimilation_count=schema_a.assimilation_count + schema_b.assimilation_count,
        violation_count=0,
    )


def _weighted_merge_dicts(
    dict_a: dict[str, float],
    dict_b: dict[str, float],
    w_a: float,
    w_b: float,
) -> dict[str, float]:
    """Weighted merge of two frequency dictionaries."""
    all_keys = set(dict_a) | set(dict_b)
    return {
        key: dict_a.get(key, 0.0) * w_a + dict_b.get(key, 0.0) * w_b for key in all_keys
    }


# ── Serialization ─────────────────────────────────────────────────────────


def schema_to_dict(schema: Schema) -> dict:
    """Serialize schema to JSON-compatible dict."""
    return {
        "schema_id": schema.schema_id,
        "domain": schema.domain,
        "label": schema.label,
        "entity_signature": schema.entity_signature,
        "relationship_types": [list(r) for r in schema.relationship_types],
        "tag_signature": schema.tag_signature,
        "consistency_threshold": schema.consistency_threshold,
        "formation_count": schema.formation_count,
        "assimilation_count": schema.assimilation_count,
        "violation_count": schema.violation_count,
        "last_updated_hours": schema.last_updated_hours,
    }


def schema_from_dict(data: dict) -> Schema:
    """Deserialize schema from dict."""
    return Schema(
        schema_id=data.get("schema_id", ""),
        domain=data.get("domain", ""),
        label=data.get("label", ""),
        entity_signature=data.get("entity_signature", {}),
        relationship_types=[tuple(r) for r in data.get("relationship_types", [])],
        tag_signature=data.get("tag_signature", {}),
        consistency_threshold=data.get("consistency_threshold", _HIGH_MATCH_THRESHOLD),
        formation_count=data.get("formation_count", 0),
        assimilation_count=data.get("assimilation_count", 0),
        violation_count=data.get("violation_count", 0),
        last_updated_hours=data.get("last_updated_hours", 0.0),
    )
