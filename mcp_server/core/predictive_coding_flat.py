"""Flat 4-signal novelty computation for the write gate.

Embedding, entity, temporal, and structural novelty signals used by
the remember handler and predictive coding gate.

Provenance: Friston 2005 grounds the CONCEPT — gating writes by prediction
error / novelty — not the specific weights, timescales, or fallback priors
below. Those are engineering defaults. The honesty discriminator is the
per-constant disclaimer, not the citation (see docs/provenance/
paper-implementation-audit.md, Wave 3). The combination weights are validated
end-to-end: the resulting flat scorer separates novel content from duplicates
at ROC-AUC=0.9998 (flat mode, benchmarks/gate_precision, 2026-06-11) — the
hierarchical alternative scored only 0.5514 on the same corpus, which is why
flat is the default path.

References:
    Friston K (2005) A theory of cortical responses.
        Phil Trans R Soc B 360:815-836 — concept only (prediction-error gating).

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
        # source: engineering default — neutral prior (mid-scale) when there is
        # no similarity evidence to judge novelty either way.
        return 0.5
    return max(0.0, min(1.0, 1.0 - max(similarities)))


# -- Entity novelty -----------------------------------------------------------


def compute_entity_novelty(
    new_entity_names: list[str] | set[str],
    known_entity_names: set[str],
) -> float:
    """Fraction of entities that are truly new. 0.5 if none extracted."""
    if not new_entity_names:
        # source: engineering default — neutral prior when no entities were
        # extracted (no evidence either way).
        return 0.5
    truly_new = sum(1 for e in new_entity_names if e not in known_entity_names)
    return truly_new / len(new_entity_names)


# -- Temporal novelty ---------------------------------------------------------


def compute_temporal_novelty(hours_since_similar: float | None) -> float:
    """Temporal novelty via exponential saturation: 1 - exp(-hours/24)."""
    if hours_since_similar is None:
        # source: engineering default — mildly-novel prior when temporal
        # distance to a similar memory is unknown.
        return 0.8
    if hours_since_similar <= 0:
        return 0.0
    # source: engineering default — 24h (one-day) saturation timescale. Friston
    # 2005 motivates temporal prediction error; the timescale is not paper-set.
    return min(1.0, 1.0 - math.exp(-hours_since_similar / 24.0))


# -- Structural novelty -------------------------------------------------------


def _structural_features(content: str) -> dict[str, int | float]:
    """Extract structural shape features from content."""
    n = max(len(content), 1)
    # source: engineering default — order-of-magnitude length buckets
    # (snippet / paragraph / section / page / document) for shape comparison.
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
        # source: engineering default — mildly-novel prior when there is no
        # recent content to compare document shape against.
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
    # source: engineering default — hand-tuned blend (embedding-dominant, then
    # entity / temporal / structural). NOT from Friston 2005. Validated
    # end-to-end: this blend yields ROC-AUC=0.9998 separating novel from
    # duplicate content (flat mode, benchmarks/gate_precision, 2026-06-11).
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
