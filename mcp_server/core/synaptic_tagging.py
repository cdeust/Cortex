"""Synaptic Tagging & Capture — retroactive memory strengthening.

Based on Frey & Morris (1997): a weak memory (early-phase LTP) can be
retroactively promoted to a strong memory (late-phase LTP) when a subsequent
high-importance event shares entities with it. The biological mechanism
involves protein synthesis tags that mark synapses for later consolidation.

In JARVIS: when a new high-importance memory is stored, we scan for older
weak memories that share entities. Those weak memories get "tagged" — their
importance and heat are boosted, making them resist compression and decay.

This implements the "synaptic tag" as a metadata field: memories that have
been retroactively promoted carry a tag_source_id pointing to the strong
memory that promoted them.

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

# ── Defaults ──────────────────────────────────────────────────────────────

# Minimum importance of the new memory to trigger tagging
_DEFAULT_TRIGGER_IMPORTANCE: float = 0.7

# Maximum importance of old memories eligible for promotion
# (already-strong memories don't need tagging)
_DEFAULT_MAX_WEAK_IMPORTANCE: float = 0.5

# Minimum entity overlap ratio to consider memories related
_DEFAULT_MIN_OVERLAP: float = 0.3

# How much to boost the weak memory's importance (additive)
_DEFAULT_IMPORTANCE_BOOST: float = 0.25

# How much to boost the weak memory's heat (multiplicative reheat)
_DEFAULT_HEAT_BOOST: float = 1.5

# Maximum age (hours) of weak memories eligible for tagging
# Biological window: ~1-6 hours for synaptic tag capture
_DEFAULT_TAG_WINDOW_HOURS: float = 48.0

# Maximum number of memories to promote per tagging event
_DEFAULT_MAX_PROMOTIONS: int = 5


def _score_candidate(
    mem: dict[str, Any],
    new_memory_entities: set[str],
    max_weak_importance: float,
    tag_window_hours: float,
    min_overlap: float,
) -> tuple[float, dict[str, Any]] | None:
    """Score a single memory as a tagging candidate.

    Returns (overlap, candidate_dict) or None if ineligible.
    """
    if mem.get("importance", 0) > max_weak_importance:
        return None
    if mem.get("age_hours", 999) > tag_window_hours:
        return None

    mem_entities = mem.get("entities", set())
    if not mem_entities:
        return None

    intersection = new_memory_entities & mem_entities
    if not intersection:
        return None

    # Szymkiewicz-Simpson overlap coefficient
    overlap = len(intersection) / min(len(new_memory_entities), len(mem_entities))
    if overlap < min_overlap:
        return None

    return (
        overlap,
        {
            "memory_id": mem["id"],
            "overlap": round(overlap, 4),
            "matched_entities": sorted(intersection),
        },
    )


def find_tagging_candidates(
    new_memory_entities: set[str],
    new_memory_importance: float,
    existing_memories: list[dict[str, Any]],
    trigger_importance: float = _DEFAULT_TRIGGER_IMPORTANCE,
    max_weak_importance: float = _DEFAULT_MAX_WEAK_IMPORTANCE,
    min_overlap: float = _DEFAULT_MIN_OVERLAP,
    tag_window_hours: float = _DEFAULT_TAG_WINDOW_HOURS,
    max_promotions: int = _DEFAULT_MAX_PROMOTIONS,
) -> list[dict[str, Any]]:
    """Find weak memories that should be retroactively promoted.

    Algorithm:
      1. Check trigger condition (importance >= trigger_importance).
      2. Score each eligible memory by entity overlap.
      3. Rank by overlap, return top max_promotions.

    Returns
    -------
    List of dicts with 'memory_id', 'overlap', and 'matched_entities'.
    """
    if new_memory_importance < trigger_importance or not new_memory_entities:
        return []

    candidates: list[tuple[float, dict[str, Any]]] = []
    for mem in existing_memories:
        result = _score_candidate(
            mem,
            new_memory_entities,
            max_weak_importance,
            tag_window_hours,
            min_overlap,
        )
        if result is not None:
            candidates.append(result)

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:max_promotions]]


def compute_tag_boosts(
    overlap: float,
    current_importance: float,
    current_heat: float,
    importance_boost: float = _DEFAULT_IMPORTANCE_BOOST,
    heat_boost: float = _DEFAULT_HEAT_BOOST,
) -> dict[str, float]:
    """Compute the boost values for a tagged memory.

    The boost scales with overlap — higher overlap = stronger promotion.

    Parameters
    ----------
    overlap : Entity overlap ratio (0-1).
    current_importance : Current importance of the weak memory.
    current_heat : Current heat of the weak memory.
    importance_boost : Base additive importance boost.
    heat_boost : Base multiplicative heat boost.

    Returns
    -------
    Dict with 'new_importance' and 'new_heat'.
    """
    scaled_importance = importance_boost * overlap
    new_importance = min(1.0, current_importance + scaled_importance)

    scaled_heat = 1.0 + (heat_boost - 1.0) * overlap
    new_heat = min(1.0, current_heat * scaled_heat)

    return {
        "new_importance": round(new_importance, 4),
        "new_heat": round(new_heat, 4),
        "importance_delta": round(new_importance - current_importance, 4),
        "heat_delta": round(new_heat - current_heat, 4),
    }


def _boost_candidate(
    candidate: dict[str, Any],
    existing_memories: list[dict[str, Any]],
    importance_boost: float,
    heat_boost: float,
) -> dict[str, Any] | None:
    """Look up the candidate memory and compute its boost values."""
    mem = next(
        (m for m in existing_memories if m["id"] == candidate["memory_id"]),
        None,
    )
    if not mem:
        return None
    boosts = compute_tag_boosts(
        overlap=candidate["overlap"],
        current_importance=mem.get("importance", 0.5),
        current_heat=mem.get("heat", 0.1),
        importance_boost=importance_boost,
        heat_boost=heat_boost,
    )
    return {**candidate, **boosts}


def apply_synaptic_tags(
    new_memory_entities: set[str],
    new_memory_importance: float,
    existing_memories: list[dict[str, Any]],
    trigger_importance: float = _DEFAULT_TRIGGER_IMPORTANCE,
    max_weak_importance: float = _DEFAULT_MAX_WEAK_IMPORTANCE,
    min_overlap: float = _DEFAULT_MIN_OVERLAP,
    tag_window_hours: float = _DEFAULT_TAG_WINDOW_HOURS,
    max_promotions: int = _DEFAULT_MAX_PROMOTIONS,
    importance_boost: float = _DEFAULT_IMPORTANCE_BOOST,
    heat_boost: float = _DEFAULT_HEAT_BOOST,
) -> list[dict[str, Any]]:
    """Full pipeline: find candidates and compute their boost values."""
    candidates = find_tagging_candidates(
        new_memory_entities=new_memory_entities,
        new_memory_importance=new_memory_importance,
        existing_memories=existing_memories,
        trigger_importance=trigger_importance,
        max_weak_importance=max_weak_importance,
        min_overlap=min_overlap,
        tag_window_hours=tag_window_hours,
        max_promotions=max_promotions,
    )

    results = []
    for candidate in candidates:
        boosted = _boost_candidate(
            candidate,
            existing_memories,
            importance_boost,
            heat_boost,
        )
        if boosted is not None:
            results.append(boosted)

    return results
