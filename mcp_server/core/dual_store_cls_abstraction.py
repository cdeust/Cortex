"""Schema abstraction, clustering, and consistency checking for CLS.

Extracted from dual_store_cls.py: greedy embedding clustering,
recurring pattern filtering, contradiction detection, and
keyword-frequency schema abstraction.

Pure business logic -- no I/O.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _find_cluster_members(
    seed_idx: int,
    seed_emb: Any,
    memories: list[dict[str, Any]],
    assigned: set[int],
    similarity_fn: Any,
    threshold: float,
) -> list[dict[str, Any]]:
    """Find all unassigned memories similar to the seed."""
    members: list[dict[str, Any]] = []
    for j in range(seed_idx + 1, len(memories)):
        if j in assigned:
            continue
        emb_b = memories[j].get("embedding")
        if emb_b is None:
            continue
        if similarity_fn(seed_emb, emb_b) >= threshold:
            members.append(memories[j])
            assigned.add(j)
    return members


def cluster_by_similarity(
    memories: list[dict[str, Any]],
    similarity_fn,
    threshold: float = 0.6,
) -> list[list[dict[str, Any]]]:
    """Greedy clustering of memories by embedding similarity.

    Parameters
    ----------
    memories:
        Each dict must have an "embedding" field (bytes or vector).
    similarity_fn:
        Callable(emb_a, emb_b) -> float in [0, 1].
    threshold:
        Minimum similarity to join a cluster.

    Returns list of clusters (each a list of memories).
    """
    if not memories:
        return []

    clusters: list[list[dict]] = []
    assigned: set[int] = set()

    for i, mem in enumerate(memories):
        if i in assigned:
            continue
        assigned.add(i)
        emb_a = mem.get("embedding")
        members = (
            _find_cluster_members(
                i, emb_a, memories, assigned, similarity_fn, threshold
            )
            if emb_a is not None
            else []
        )
        clusters.append([mem] + members)

    return clusters


def filter_recurring_patterns(
    clusters: list[list[dict[str, Any]]],
    min_occurrences: int = 3,
    min_sessions: int = 2,
) -> list[dict[str, Any]]:
    """Filter clusters to only those that represent recurring patterns.

    A recurring pattern must appear in at least `min_occurrences` memories
    across at least `min_sessions` distinct sessions.
    """
    patterns: list[dict] = []

    for cluster in clusters:
        if len(cluster) < min_occurrences:
            continue

        sessions = set()
        for mem in cluster:
            sid = mem.get("session_id") or mem.get("source", "")
            if sid:
                sessions.add(sid)

        if len(sessions) < min_sessions:
            continue

        patterns.append(
            {
                "memories": cluster,
                "count": len(cluster),
                "session_count": len(sessions),
                "memory_ids": [m.get("id") for m in cluster if m.get("id")],
            }
        )

    return patterns


# ---------------------------------------------------------------------------
# Consistency checking
# ---------------------------------------------------------------------------

_NEGATION_RE = re.compile(
    r"\b(not|don't|doesn't|no longer|replaced|switched from|deprecated|never)\b",
    re.IGNORECASE,
)


def check_consistency(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Check a cluster of memories for contradictions.

    Simple heuristic: if one memory has negation words and another doesn't,
    flag as potential contradiction.
    """
    if len(memories) < 2:
        return {"consistent": True, "contradictions": []}

    contradictions: list[str] = []
    negated: list[dict] = []
    positive: list[dict] = []

    for mem in memories:
        content = mem.get("content", "")
        if _NEGATION_RE.search(content):
            negated.append(mem)
        else:
            positive.append(mem)

    if negated and positive:
        for neg in negated[:3]:
            contradictions.append(
                f"Potential contradiction: '{neg.get('content', '')[:100]}...'"
            )

    return {
        "consistent": len(contradictions) == 0,
        "contradictions": contradictions,
    }


# ---------------------------------------------------------------------------
# Schema abstraction
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "is",
        "it",
        "this",
        "that",
        "are",
        "was",
        "be",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "from",
        "as",
        "if",
        "then",
        "than",
        "so",
        "just",
        "also",
        "its",
        "their",
        "them",
        "they",
        "we",
        "our",
        "i",
        "you",
        "he",
        "she",
        "my",
        "your",
        "his",
        "her",
    }
)


def _extract_key_words(
    memories: list[dict[str, Any]],
) -> tuple[list[str], int]:
    """Extract frequently occurring non-stopwords across memories."""
    n = len(memories)
    word_counts: dict[str, int] = {}

    for mem in memories:
        content = mem.get("content", "")
        words = set(re.findall(r"\b\w+\b", content.lower()))
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1

    first_content = memories[0].get("content", "")
    first_words = re.findall(r"\b\w+\b", first_content.lower())
    first_order = {w: i for i, w in enumerate(first_words)}

    threshold = max(1, n * 0.5)
    key_words = [
        w
        for w in word_counts
        if word_counts[w] >= threshold and w.lower() not in _STOP_WORDS and len(w) > 1
    ]

    key_words.sort(key=lambda w: (first_order.get(w, 9999), w))
    return key_words[:15], n


def _extract_common_tags(
    memories: list[dict[str, Any]],
    n: int,
) -> list[str]:
    """Extract tags appearing in at least 50% of memories."""
    all_tags: dict[str, int] = {}
    for mem in memories:
        for tag in mem.get("tags", []):
            if isinstance(tag, str):
                all_tags[tag] = all_tags.get(tag, 0) + 1
    return [t for t, c in all_tags.items() if c >= max(1, n * 0.5)]


def abstract_to_schema(memories: list[dict[str, Any]]) -> str:
    """Extract a generalized schema statement from a cluster."""
    if not memories:
        return ""

    key_words, n = _extract_key_words(memories)

    if not key_words:
        return f"Recurring pattern across {n} observations"

    key_phrase = " ".join(key_words)
    common_tags = _extract_common_tags(memories, n)

    schema = f"Recurring pattern across {n} observations: {key_phrase}"
    if common_tags:
        schema += f" [{', '.join(common_tags[:5])}]"

    return schema
