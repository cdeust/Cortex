"""Active memory curation — merge/link/create decisions and self-improvement.

Implements:
  - Ingestion decisions: merge near-duplicates, link related, create new
  - Contradiction detection: negation + action divergence
  - Memify self-improvement: prune, strengthen, reweight, derive

Pure business logic — no I/O. Receives data, returns decisions/actions.
"""

from __future__ import annotations

import re
from typing import Any

# ── Constants ─────────────────────────────────────────────────────────────

_NEGATION_RE = re.compile(
    r"\b(not|don't|doesn't|no longer|replaced|switched from|"
    r"deprecated|never|removed|stopped|avoid)\b",
    re.IGNORECASE,
)

_ACTION_RE = re.compile(
    r"\b(use|using|prefer|run|install|deploy|build|create|"
    r"configure|set|enable|disable|switch|migrate)\b",
    re.IGNORECASE,
)

# Similarity thresholds
MERGE_THRESHOLD = 0.85
LINK_LOW = 0.6
LINK_HIGH = 0.85


# ── Ingestion Decisions ───────────────────────────────────────────────────


def decide_curation_action(
    similarity: float,
    has_textual_overlap: bool,
    merge_threshold: float = MERGE_THRESHOLD,
    link_low: float = LINK_LOW,
) -> str:
    """Decide what to do when storing a memory that has similar existing ones.

    Returns one of: "merge", "link", "create".
    """
    if similarity >= merge_threshold and has_textual_overlap:
        return "merge"
    elif similarity >= link_low:
        return "link"
    else:
        return "create"


def compute_textual_overlap(content_a: str, content_b: str) -> float:
    """Jaccard similarity between word sets of two texts."""
    words_a = set(re.findall(r"\b\w+\b", content_a.lower()))
    words_b = set(re.findall(r"\b\w+\b", content_b.lower()))
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def merge_contents(existing_content: str, new_content: str) -> str:
    """Merge two memory contents, avoiding pure duplication."""
    if new_content.strip() in existing_content:
        return existing_content
    if existing_content.strip() in new_content:
        return new_content
    return f"{existing_content}\n{new_content}"


def merge_tags(existing_tags: list[str], new_tags: list[str]) -> list[str]:
    """Union of tag sets, preserving order."""
    seen = set()
    merged: list[str] = []
    for tag in existing_tags + new_tags:
        if tag not in seen:
            seen.add(tag)
            merged.append(tag)
    return merged


# ── Contradiction Detection ───────────────────────────────────────────────


def _check_single_contradiction(
    mem: dict,
    new_has_negation: bool,
    new_actions: set[str],
) -> dict[str, Any] | None:
    """Check one memory for contradiction against new content signals."""
    existing_content = mem.get("content", "")
    existing_has_negation = bool(_NEGATION_RE.search(existing_content))
    mem_id = mem.get("id")

    if new_has_negation != existing_has_negation:
        return {
            "memory_id": mem_id,
            "type": "negation_mismatch",
            "description": f"Negation conflict with memory {mem_id}",
            "confidence_penalty": 0.2,
        }

    existing_actions = set(_ACTION_RE.findall(existing_content.lower()))
    if new_actions and existing_actions and not (new_actions & existing_actions):
        return {
            "memory_id": mem_id,
            "type": "action_divergence",
            "description": f"Different actions on similar topic (memory {mem_id})",
            "confidence_penalty": 0.1,
        }
    return None


def detect_contradictions(
    new_content: str,
    similar_memories: list[dict[str, Any]],
    similarity_threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """Detect potential contradictions between new content and existing memories.

    Returns list of {memory_id, type, description, confidence_penalty}.
    """
    new_has_negation = bool(_NEGATION_RE.search(new_content))
    new_actions = set(_ACTION_RE.findall(new_content.lower()))

    contradictions: list[dict] = []
    for mem in similar_memories:
        result = _check_single_contradiction(mem, new_has_negation, new_actions)
        if result is not None:
            contradictions.append(result)
    return contradictions


# ── Memify Self-Improvement ───────────────────────────────────────────────


def identify_prunable(
    memories: list[dict[str, Any]],
    heat_threshold: float = 0.01,
    confidence_threshold: float = 0.3,
) -> list[int]:
    """Identify memories that should be pruned.

    Prune criteria: heat < threshold AND confidence < threshold AND access_count == 0.
    """
    return [
        m["id"]
        for m in memories
        if m.get("heat", 1.0) < heat_threshold
        and m.get("confidence", 1.0) < confidence_threshold
        and m.get("access_count", 0) == 0
    ]


def identify_strengtheneable(
    memories: list[dict[str, Any]],
    min_access: int = 5,
    min_confidence: float = 0.8,
    boost_amount: float = 0.1,
) -> list[tuple[int, float]]:
    """Identify memories that deserve importance boost.

    Returns list of (memory_id, new_importance).
    """
    results: list[tuple[int, float]] = []
    for mem in memories:
        if (
            mem.get("access_count", 0) >= min_access
            and mem.get("confidence", 0) >= min_confidence
        ):
            current = mem.get("importance", 0.5)
            new_importance = min(1.0, current + boost_amount)
            if new_importance > current:
                results.append((mem["id"], new_importance))
    return results


def compute_relationship_reweights(
    relationships: list[dict[str, Any]],
    entity_heats: dict[int, float],
    hot_threshold: float = 0.7,
    cold_threshold: float = 0.1,
    hot_boost: float = 0.5,
    cold_decay: float = 0.9,
) -> list[tuple[int, float]]:
    """Compute relationship weight adjustments based on entity heat.

    Returns list of (relationship_id, new_weight).
    """
    updates: list[tuple[int, float]] = []
    for rel in relationships:
        src_heat = entity_heats.get(rel.get("source_entity_id", 0), 0.5)
        tgt_heat = entity_heats.get(rel.get("target_entity_id", 0), 0.5)
        avg_heat = (src_heat + tgt_heat) / 2
        current_weight = rel.get("weight", 1.0)

        if avg_heat > hot_threshold:
            new_weight = current_weight + hot_boost
        elif avg_heat < cold_threshold:
            new_weight = current_weight * cold_decay
        else:
            continue

        updates.append((rel["id"], round(new_weight, 3)))
    return updates


def identify_derivable_facts(
    relationships: list[dict[str, Any]],
    entity_names: dict[int, str],
    weight_threshold: float = 10.0,
) -> list[str]:
    """Generate synthetic facts from high-weight relationships.

    Returns list of fact strings.
    """
    facts: list[str] = []
    for rel in relationships:
        if rel.get("weight", 0) >= weight_threshold:
            src_name = entity_names.get(rel.get("source_entity_id", 0), "?")
            tgt_name = entity_names.get(rel.get("target_entity_id", 0), "?")
            rel_type = rel.get("relationship_type", "related_to")
            facts.append(
                f"{src_name} and {tgt_name} are strongly linked "
                f"({rel_type}, weight={rel['weight']:.1f})"
            )
    return facts
