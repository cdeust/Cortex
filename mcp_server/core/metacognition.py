"""Metacognition — coverage assessment, gap detection, and cognitive load management.

Implements:
  - Coverage assessment: 4-signal weighted analysis (density, entity, recency, confidence)
  - Gap detection: 5 gap types (isolated, stale, low-confidence, missing links, unresolved)
  - Cognitive load management: Cowan's 4+/-1 chunk limit with primacy-recency positioning

Coverage, chunking, and context management live in metacognition_analysis.py.
This module provides gap detection.

Pure business logic — no I/O. Receives pre-fetched data, returns analyses.
"""

from __future__ import annotations

from typing import Any

# ── Gap Detection ─────────────────────────────────────────────────────────


def detect_isolated_entities(
    entities: list[dict[str, Any]],
    relationship_counts: dict[int, int],
) -> list[dict[str, Any]]:
    """Find entities with zero or one connection.

    Parameters
    ----------
    entities:
        List of entity dicts with "id" and "name".
    relationship_counts:
        Map of entity_id -> number of relationships.
    """
    gaps: list[dict] = []
    for ent in entities:
        eid = ent["id"]
        degree = relationship_counts.get(eid, 0)
        if degree <= 1:
            severity = 0.6 if degree == 0 else 0.4
            gaps.append(
                {
                    "type": "isolated_entity",
                    "description": f"Entity '{ent['name']}' has only {degree} connection(s)",
                    "severity": severity,
                    "entities": [ent["name"]],
                    "suggestion": f"Add context or relationships for '{ent['name']}'",
                }
            )
    return gaps


def detect_stale_regions(
    memories: list[dict[str, Any]],
    heat_threshold: float = 0.3,
    min_stale: int = 2,
) -> list[dict[str, Any]]:
    """Find groups of stale (low-heat) memories.

    Returns gap entries for directories or domains with multiple stale memories.
    """
    stale_by_domain: dict[str, list[dict]] = {}
    for mem in memories:
        if mem.get("heat", 1.0) < heat_threshold:
            domain = mem.get("domain", "unknown")
            stale_by_domain.setdefault(domain, []).append(mem)

    gaps: list[dict] = []
    for domain, stale_mems in stale_by_domain.items():
        if len(stale_mems) >= min_stale:
            severity = min(0.9, 0.3 + len(stale_mems) * 0.1)
            gaps.append(
                {
                    "type": "stale_region",
                    "description": f"{len(stale_mems)} stale memories in domain '{domain}'",
                    "severity": round(severity, 2),
                    "entities": [],
                    "suggestion": f"Review or refresh memories in '{domain}'",
                }
            )
    return gaps


def detect_low_confidence(
    memories: list[dict[str, Any]],
    confidence_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Find memories with low confidence scores."""
    low_conf = [m for m in memories if m.get("confidence", 1.0) < confidence_threshold]
    if not low_conf:
        return []

    severity = min(0.8, 0.3 + len(low_conf) * 0.1)
    return [
        {
            "type": "low_confidence",
            "description": f"{len(low_conf)} memories have confidence < {confidence_threshold}",
            "severity": round(severity, 2),
            "entities": [],
            "suggestion": "Verify or strengthen low-confidence memories",
        }
    ]


def detect_missing_connections(
    co_occurring_pairs: list[tuple[str, str]],
    existing_relationships: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Find entity pairs that co-occur in memories but have no graph edge.

    Parameters
    ----------
    co_occurring_pairs:
        List of (entity_name_a, entity_name_b) that appear together in memories.
    existing_relationships:
        Set of (entity_name_a, entity_name_b) that have relationship edges.
    """
    missing = [
        (a, b)
        for a, b in co_occurring_pairs
        if (a, b) not in existing_relationships and (b, a) not in existing_relationships
    ]
    if not missing:
        return []

    severity = min(0.7, 0.2 + len(missing) * 0.1)
    entity_names = list({name for pair in missing[:5] for name in pair})
    return [
        {
            "type": "missing_connection",
            "description": f"{len(missing)} entity pairs co-occur but have no relationship",
            "severity": round(severity, 2),
            "entities": entity_names,
            "suggestion": "Consider linking frequently co-occurring entities",
        }
    ]


def detect_unresolved_errors(
    error_entities: list[dict[str, Any]],
    resolved_entity_ids: set[int],
) -> list[dict[str, Any]]:
    """Find error entities with no 'resolved_by' relationship.

    Parameters
    ----------
    error_entities:
        Entities of type "error" or "exception".
    resolved_entity_ids:
        Set of entity IDs that have a "resolved_by" relationship.
    """
    unresolved = [e for e in error_entities if e["id"] not in resolved_entity_ids]
    if not unresolved:
        return []

    return [
        {
            "type": "unresolved_error",
            "description": f"{len(unresolved)} error(s) recorded without resolution",
            "severity": 0.5,
            "entities": [e["name"] for e in unresolved[:5]],
            "suggestion": "Record fix/resolution for outstanding errors",
        }
    ]


def detect_all_gaps(
    entities: list[dict[str, Any]],
    relationship_counts: dict[int, int],
    memories: list[dict[str, Any]],
    co_occurring_pairs: list[tuple[str, str]],
    existing_relationships: set[tuple[str, str]],
    error_entities: list[dict[str, Any]],
    resolved_entity_ids: set[int],
    heat_threshold: float = 0.3,
    confidence_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Run all gap detectors and return combined results sorted by severity."""
    gaps: list[dict] = []
    gaps.extend(detect_isolated_entities(entities, relationship_counts))
    gaps.extend(detect_stale_regions(memories, heat_threshold))
    gaps.extend(detect_low_confidence(memories, confidence_threshold))
    gaps.extend(detect_missing_connections(co_occurring_pairs, existing_relationships))
    gaps.extend(detect_unresolved_errors(error_entities, resolved_entity_ids))
    gaps.sort(key=lambda g: g["severity"], reverse=True)
    return gaps
