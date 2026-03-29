"""Interference management — orthogonalization, retrieval suppression, and domain metrics.

Memory interference is the primary cause of forgetting in both biological and
artificial systems. Detection helpers live in interference_detection.py;
this module provides resolution (orthogonalization), retrieval suppression,
domain pressure metrics, and re-exports all public symbols.

References:
    Anderson MC, Neely JH (1996) Interference and inhibition in memory retrieval.
    Wixted JT (2004) The psychology and neuroscience of forgetting.
    Yassa MA, Stark CEL (2011) Pattern separation in the hippocampus.

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.shared.linear_algebra import (
    add,
    cosine_similarity,
    dot,
    norm,
    scale,
    subtract,
)

# ── Configuration ─────────────────────────────────────────────────────────

_ORTHOGONALIZATION_RATE = 0.15
_MIN_ORTHOGONAL_SIMILARITY = 0.2
_RETRIEVAL_SUPPRESSION = 0.3
_INTERFERENCE_THRESHOLD = 0.7


# ── Orthogonalization Helpers ─────────────────────────────────────────────


def _project_away(
    vec: list[float],
    basis: list[float],
    rate: float,
) -> list[float]:
    """Remove a fraction of vec's projection onto basis."""
    basis_norm_sq = sum(v * v for v in basis)
    if basis_norm_sq < 1e-10:
        return list(vec)
    proj_coeff = dot(vec, basis) / basis_norm_sq
    projection = scale(basis, proj_coeff * rate * 0.5)
    return subtract(vec, projection)


def _renormalize(vec: list[float], fallback: list[float]) -> list[float]:
    """Normalize vec to unit length, falling back if degenerate."""
    n = norm(vec)
    if n > 1e-10:
        return scale(vec, 1.0 / n)
    return list(fallback)


def _backoff_to_minimum(
    new_a: list[float],
    new_b: list[float],
    orig_a: list[float],
    orig_b: list[float],
    new_sim: float,
    current_sim: float,
    min_similarity: float,
) -> tuple[list[float], list[float], float]:
    """Interpolate back toward originals if similarity dropped too far."""
    t = (min_similarity - new_sim) / max(current_sim - new_sim, 1e-10)
    t = min(1.0, max(0.0, t))
    blended_a = add(scale(new_a, 1 - t), scale(orig_a, t))
    blended_b = add(scale(new_b, 1 - t), scale(orig_b, t))
    blended_a = _renormalize(blended_a, orig_a)
    blended_b = _renormalize(blended_b, orig_b)
    final_sim = cosine_similarity(blended_a, blended_b)
    return blended_a, blended_b, final_sim


# ── Orthogonalization ─────────────────────────────────────────────────────


def orthogonalize_pair(
    embedding_a: list[float],
    embedding_b: list[float],
    *,
    rate: float = _ORTHOGONALIZATION_RATE,
    min_similarity: float = _MIN_ORTHOGONAL_SIMILARITY,
) -> tuple[list[float], list[float], float]:
    """Gradually push two interfering embeddings apart (sleep-dependent).

    One step of gradual rotation per call. Multiple sleep cycles
    achieve full separation. Returns (new_a, new_b, remaining_sim).
    """
    if len(embedding_a) != len(embedding_b):
        return list(embedding_a), list(embedding_b), 0.0

    current_sim = cosine_similarity(embedding_a, embedding_b)
    if current_sim <= min_similarity:
        return list(embedding_a), list(embedding_b), current_sim

    new_a = _renormalize(_project_away(embedding_a, embedding_b, rate), embedding_a)
    new_b = _renormalize(_project_away(embedding_b, embedding_a, rate), embedding_b)

    new_sim = cosine_similarity(new_a, new_b)
    if new_sim < min_similarity:
        new_a, new_b, new_sim = _backoff_to_minimum(
            new_a,
            new_b,
            embedding_a,
            embedding_b,
            new_sim,
            current_sim,
            min_similarity,
        )

    return new_a, new_b, round(new_sim, 6)


# ── Retrieval Suppression ────────────────────────────────────────────────


def compute_retrieval_suppression(
    target_score: float,
    competitor_scores: list[float],
    *,
    suppression_factor: float = _RETRIEVAL_SUPPRESSION,
) -> float:
    """Compute retrieval suppression from competing memories.

    When multiple similar memories compete during retrieval, the winner
    suppresses the losers via lateral inhibition. This models the
    retrieval-induced forgetting (RIF) effect.

    Args:
        target_score: Retrieval score of the memory being evaluated.
        competitor_scores: Retrieval scores of competing (similar) memories.
        suppression_factor: How much each competitor suppresses this memory.

    Returns:
        Suppressed retrieval score [0, target_score].
    """
    if not competitor_scores:
        return target_score

    stronger_competitors = [s for s in competitor_scores if s > target_score]
    if not stronger_competitors:
        return target_score

    total_suppression = sum(
        (s - target_score) * suppression_factor for s in stronger_competitors
    )

    return max(0.0, target_score - total_suppression)


# ── Domain Interference Metrics ──────────────────────────────────────────


def _compute_pairwise_stats(
    embeddings: list[list[float]],
    n: int,
    threshold: float,
) -> tuple[list[float], int, int]:
    """Compute max similarities and interference pair counts."""
    max_sims: list[float] = []
    interference_pairs = 0
    total_pairs = 0

    for i in range(n):
        best_sim = 0.0
        for j in range(n):
            if i == j:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[j])
            best_sim = max(best_sim, sim)
            if sim >= threshold:
                interference_pairs += 1
            total_pairs += 1
        max_sims.append(best_sim)

    return max_sims, interference_pairs, total_pairs


def _classify_pressure(avg_score: float) -> str:
    """Classify interference pressure level from average score."""
    if avg_score >= 0.5:
        return "critical"
    if avg_score >= 0.3:
        return "high"
    if avg_score >= 0.1:
        return "medium"
    return "low"


_LOW_PRESSURE = {
    "mean_max_similarity": 0.0,
    "interfering_pair_fraction": 0.0,
    "avg_interference_score": 0.0,
    "pressure_level": "low",
}


def compute_domain_interference_pressure(
    embeddings: list[list[float]],
    *,
    threshold: float = _INTERFERENCE_THRESHOLD,
    sample_limit: int = 100,
) -> dict[str, float]:
    """Compute aggregate interference metrics for a domain.

    Args:
        embeddings: All memory embeddings in the domain.
        threshold: Similarity threshold for interference.
        sample_limit: Max pairwise comparisons (for performance).

    Returns:
        Dict with: mean_max_similarity, interfering_pair_fraction,
        avg_interference_score, pressure_level (low/medium/high/critical).
    """
    if len(embeddings) < 2:
        return dict(_LOW_PRESSURE)

    n = min(len(embeddings), sample_limit)
    max_sims, interference_pairs, total_pairs = _compute_pairwise_stats(
        embeddings, n, threshold
    )

    mean_max = sum(max_sims) / len(max_sims) if max_sims else 0.0
    pair_fraction = interference_pairs / max(total_pairs, 1)
    avg_score = mean_max * pair_fraction

    return {
        "mean_max_similarity": round(mean_max, 4),
        "interfering_pair_fraction": round(pair_fraction, 4),
        "avg_interference_score": round(avg_score, 4),
        "pressure_level": _classify_pressure(avg_score),
    }
