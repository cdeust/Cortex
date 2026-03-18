"""Flat 4-signal novelty computation for the write gate.

Embedding, entity, temporal, and structural novelty signals used by
the remember handler and predictive coding gate.

References:
    Friston K (2005) A theory of cortical responses.
        Phil Trans R Soc B 360:815-836

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
import re

# Shared regex patterns (also used by hierarchical levels)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_FILE_PATH_RE = re.compile(r"(?:\.{0,2}/)?(?:[\w@.-]+/)+[\w@.-]+\.\w+")
_URL_RE = re.compile(r"https?://\S+")
_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_LIST_RE = re.compile(r"^[\s]*[-*+]\s+\S", re.MULTILINE)


# -- Embedding novelty --------------------------------------------------------


def compute_embedding_novelty(similarities: list[float]) -> float:
    """Embedding novelty = 1 - max(similarities). 0.5 if no data."""
    if not similarities:
        return 0.5
    return max(0.0, min(1.0, 1.0 - max(similarities)))


# -- Entity novelty -----------------------------------------------------------


def compute_entity_novelty(
    new_entity_names: list[str] | set[str],
    known_entity_names: set[str],
) -> float:
    """Fraction of entities that are truly new. 0.5 if none extracted."""
    if not new_entity_names:
        return 0.5
    truly_new = sum(1 for e in new_entity_names if e not in known_entity_names)
    return truly_new / len(new_entity_names)


# -- Temporal novelty ---------------------------------------------------------


def compute_temporal_novelty(hours_since_similar: float | None) -> float:
    """Temporal novelty via exponential saturation: 1 - exp(-hours/24)."""
    if hours_since_similar is None:
        return 0.8
    if hours_since_similar <= 0:
        return 0.0
    return min(1.0, 1.0 - math.exp(-hours_since_similar / 24.0))


# -- Structural novelty -------------------------------------------------------


def _structural_features(content: str) -> dict[str, int | float]:
    """Extract structural shape features from content."""
    n = max(len(content), 1)
    if n < 100:
        length_bucket = 0
    elif n < 500:
        length_bucket = 1
    elif n < 2000:
        length_bucket = 2
    elif n < 8000:
        length_bucket = 3
    else:
        length_bucket = 4

    return {
        "code_blocks": len(_CODE_BLOCK_RE.findall(content)),
        "file_refs": len(_FILE_PATH_RE.findall(content)),
        "urls": len(_URL_RE.findall(content)),
        "headings": len(_HEADING_RE.findall(content)),
        "list_items": len(_LIST_RE.findall(content)),
        "length_bucket": length_bucket,
    }


def compute_structural_novelty(content: str, recent_contents: list[str]) -> float:
    """Structural novelty by comparing document shape to recent memories."""
    if not recent_contents:
        return 0.7
    candidate = _structural_features(content)
    keys = list(candidate.keys())
    best_match = 0.0
    for existing_content in recent_contents:
        existing = _structural_features(existing_content)
        matches = sum(1 for k in keys if candidate[k] == existing[k])
        similarity = matches / len(keys)
        best_match = max(best_match, similarity)
    return max(0.0, min(1.0, 1.0 - best_match))


# -- Combined novelty ---------------------------------------------------------


def compute_novelty_score(
    embedding_novelty: float,
    entity_novelty: float,
    temporal_novelty: float,
    structural_novelty: float,
) -> float:
    """Combined novelty score from the 4-signal gate. Returns [0, 1]."""
    return (
        0.40 * embedding_novelty
        + 0.25 * entity_novelty
        + 0.20 * temporal_novelty
        + 0.15 * structural_novelty
    )


def describe_signals(
    embedding: float,
    entity: float,
    temporal: float,
    structural: float,
    combined: float,
) -> dict[str, float]:
    """Structured dict of all signal values for observability."""
    return {
        "embedding_novelty": round(embedding, 4),
        "entity_novelty": round(entity, 4),
        "temporal_novelty": round(temporal, 4),
        "structural_novelty": round(structural, 4),
        "combined_novelty": round(combined, 4),
    }
