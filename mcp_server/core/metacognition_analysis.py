"""Metacognition analysis — coverage computation, chunking, and context management.

Pure business logic — no I/O.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

# ── Coverage Assessment ───────────────────────────────────────────────────

_DENSITY_THRESHOLDS = [(6, 0.9), (3, 0.6), (1, 0.3)]
_RECENCY_THRESHOLDS = [
    (timedelta(days=1), 1.0),
    (timedelta(days=7), 0.7),
    (timedelta(days=30), 0.4),
]
_RECENCY_DEFAULT = 0.2


def _compute_density(matching_count: int) -> float:
    """Map memory count to a density signal via thresholds."""
    for threshold, score in _DENSITY_THRESHOLDS:
        if matching_count >= threshold:
            return score
    return 0.0


def _compute_recency(newest_age: timedelta | None) -> float:
    """Map newest memory age to a recency signal via thresholds."""
    if newest_age is None:
        return 0.0
    for max_age, score in _RECENCY_THRESHOLDS:
        if newest_age <= max_age:
            return score
    return _RECENCY_DEFAULT


def _classify_coverage(score: float) -> str:
    """Classify coverage as sufficient/partial/insufficient."""
    if score >= 0.7:
        return "sufficient"
    if score >= 0.4:
        return "partial"
    return "insufficient"


def compute_coverage(
    matching_count: int,
    entity_coverage: float,
    newest_age: timedelta | None,
    avg_confidence: float,
    weights: tuple[float, float, float, float] = (0.3, 0.3, 0.2, 0.2),
) -> dict[str, Any]:
    """Compute 4-signal weighted coverage score.

    Signals: density (from count), entity_coverage, recency, confidence.
    Weights default to (0.3, 0.3, 0.2, 0.2).
    """
    density = _compute_density(matching_count)
    recency = _compute_recency(newest_age)

    w_d, w_e, w_r, w_c = weights
    overall = (
        w_d * density + w_e * entity_coverage + w_r * recency + w_c * avg_confidence
    )

    return {
        "coverage": round(overall, 3),
        "density": round(density, 3),
        "entity_coverage": round(entity_coverage, 3),
        "recency": round(recency, 3),
        "confidence": round(avg_confidence, 3),
        "suggestion": _classify_coverage(overall),
        "memory_count": matching_count,
    }


# ── Chunking Helpers ─────────────────────────────────────────────────────


def _get_entities(mem: dict) -> set[str]:
    """Extract entity set from a memory's tags field."""
    tags = mem.get("tags", [])
    if isinstance(tags, str):
        tags = tags.split(",")
    return {t.strip().lower() for t in tags if t.strip()}


def _get_time(mem: dict) -> datetime | None:
    """Parse creation or last-access timestamp from a memory."""
    ts = mem.get("created_at") or mem.get("last_accessed")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _should_join_chunk(
    mem_i: dict,
    mem_j: dict,
    ents_i: set[str],
    time_i: datetime | None,
    entity_overlap_threshold: float,
    window: timedelta,
) -> bool:
    """Decide whether mem_j should join mem_i's chunk."""
    ents_j = _get_entities(mem_j)
    if _jaccard(ents_i, ents_j) >= entity_overlap_threshold:
        return True

    time_j = _get_time(mem_j)
    if time_i and time_j and abs(time_i - time_j) <= window:
        return True

    return False


def _collect_chunk(
    seed_idx: int,
    mem: dict,
    memories: list[dict[str, Any]],
    assigned: set[int],
    entity_overlap_threshold: float,
    window: timedelta,
) -> list[dict[str, Any]]:
    """Collect all unassigned memories that belong to the same chunk as mem."""
    ents_i = _get_entities(mem)
    time_i = _get_time(mem)
    members: list[dict[str, Any]] = []
    for j in range(seed_idx + 1, len(memories)):
        if j in assigned:
            continue
        if _should_join_chunk(
            mem, memories[j], ents_i, time_i, entity_overlap_threshold, window
        ):
            members.append(memories[j])
            assigned.add(j)
    return members


def chunk_memories(
    memories: list[dict[str, Any]],
    entity_overlap_threshold: float = 0.3,
    temporal_window_hours: float = 2.0,
) -> list[list[dict[str, Any]]]:
    """Group memories into chunks by entity overlap or temporal proximity.

    Two memories join the same chunk if:
      - Jaccard similarity of their entity sets >= threshold, OR
      - They were created within temporal_window_hours of each other
    """
    if not memories:
        return []

    chunks: list[list[dict]] = []
    assigned: set[int] = set()
    window = timedelta(hours=temporal_window_hours)

    for i, mem in enumerate(memories):
        if i in assigned:
            continue
        assigned.add(i)
        members = _collect_chunk(
            i, mem, memories, assigned, entity_overlap_threshold, window
        )
        chunks.append([mem] + members)

    return chunks


# ── Context Management ───────────────────────────────────────────────────

DEFAULT_MAX_CHUNKS = 5  # Cowan's 4±1


def _score_chunk(chunk: list[dict[str, Any]]) -> float:
    """Score a chunk by mean(importance * heat * confidence)."""
    if not chunk:
        return 0.0
    scores = [
        mem.get("importance", 0.5) * mem.get("heat", 0.5) * mem.get("confidence", 0.5)
        for mem in chunk
    ]
    return sum(scores) / len(scores)


def _annotate_chunk(
    chunk: list[dict[str, Any]],
    chunk_id: int,
    reason: str,
) -> list[dict[str, Any]]:
    """Add _chunk_id and _position_reason to each memory in a chunk."""
    return [{**mem, "_chunk_id": chunk_id, "_position_reason": reason} for mem in chunk]


def _position_selected_chunks(
    selected: list[tuple[int, float, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Apply primacy-recency positioning to selected chunks."""
    result: list[dict] = []

    if len(selected) >= 2:
        primacy = selected[0]
        recency = selected[1]
        middle = selected[2:]

        result.extend(_annotate_chunk(primacy[2], primacy[0], "primacy"))
        for chunk_id, _, chunk in middle:
            result.extend(_annotate_chunk(chunk, chunk_id, "middle"))
        result.extend(_annotate_chunk(recency[2], recency[0], "recency"))
    elif selected:
        result.extend(_annotate_chunk(selected[0][2], selected[0][0], "primacy"))

    return result


def manage_context(
    memories: list[dict[str, Any]],
    max_chunks: int | None = None,
) -> list[dict[str, Any]]:
    """Apply cognitive load management with primacy-recency positioning.

    Algorithm:
      1. If memories fit within max_chunks, return with metadata
      2. Chunk by entity overlap + temporal proximity
      3. Score chunks, take top max_chunks
      4. Position: highest-score at start (primacy), second-highest at end (recency)
      5. Mark overflow for summarization

    Returns memories with added _chunk_id and _position_reason fields.
    """
    if max_chunks is None:
        max_chunks = DEFAULT_MAX_CHUNKS

    if len(memories) <= max_chunks:
        return _annotate_chunk(memories, 0, "within_limit")

    chunks = chunk_memories(memories)
    scored = [(i, _score_chunk(c), c) for i, c in enumerate(chunks)]
    scored.sort(key=lambda x: x[1], reverse=True)

    selected = scored[:max_chunks]
    overflow = scored[max_chunks:]

    result = _position_selected_chunks(selected)

    for chunk_id, _, chunk in overflow:
        result.extend(_annotate_chunk(chunk, chunk_id, "overflow"))

    return result


def summarize_overflow(
    excess_memories: list[dict[str, Any]],
    target_count: int = 1,
    surprise_threshold: float = 0.7,
    importance_threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """Compress overflow memories, preserving high-value ones.

    High-surprise or high-importance memories are kept intact.
    Others are summarized into brief snippets.
    """
    preserved: list[dict] = []
    to_summarize: list[dict] = []

    for mem in excess_memories:
        surprise = mem.get("surprise", 0.0)
        importance = mem.get("importance", 0.0)
        if surprise >= surprise_threshold or importance >= importance_threshold:
            preserved.append(mem)
        else:
            to_summarize.append(mem)

    result = preserved[:]

    if to_summarize and target_count > 0:
        contents = [m.get("content", "")[:80] for m in to_summarize]
        summary_text = "; ".join(contents)
        if len(summary_text) > 300:
            summary_text = summary_text[:297] + "..."
        result.append(
            {
                "content": f"[Summary of {len(to_summarize)} memories] {summary_text}",
                "heat": max(m.get("heat", 0) for m in to_summarize),
                "importance": max(m.get("importance", 0) for m in to_summarize),
                "_position_reason": "overflow_summary",
            }
        )

    return result
