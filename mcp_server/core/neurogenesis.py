"""Neurogenesis analog and separation metrics.

Simulates adult neurogenesis: new "neurons" (embedding dimensions) are
hyperexcitable initially and gradually mature, creating temporal context
signals for natural temporal clustering. Also provides separation metrics
for monitoring pattern separation effectiveness.

References:
    Aimone JB et al. (2011) Resolving new memories: DG, neurogenesis, and
        pattern separation. Neuron 70:589-596
    Cognitive Neurodynamics (2025) Dynamic impact of adult neurogenesis
        on pattern separation in the DG neural network.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math

from mcp_server.shared.linear_algebra import (
    cosine_similarity,
    norm,
    scale,
)

# ── Configuration ─────────────────────────────────────────────────────────

_NEUROGENESIS_BOOST = 0.3
_SEPARATION_THRESHOLD = 0.75


# ── Temporal Separation Weights ──────────────────────────────────────────


def _compute_boost_magnitude(
    hours_since_creation: float,
    maturation_hours: float,
    boost: float,
) -> float:
    """Compute the neurogenesis boost magnitude based on memory maturity."""
    maturity = 1.0 - math.exp(-hours_since_creation / maturation_hours)
    immaturity = 1.0 - maturity
    return boost * immaturity


def _apply_dimension_boosts(
    weights: list[float],
    hours_since_creation: float,
    boost_magnitude: float,
) -> None:
    """Apply time-varying dimension boosts to weight vector (in-place)."""
    embedding_dim = len(weights)
    time_bucket = int(hours_since_creation / 6.0)
    boosted_start = (time_bucket * 7) % embedding_dim
    boosted_count = max(1, int(embedding_dim * 0.1))

    for i in range(boosted_count):
        dim_idx = (boosted_start + i) % embedding_dim
        weights[dim_idx] = 1.0 + boost_magnitude


def compute_temporal_separation_weights(
    hours_since_creation: float,
    embedding_dim: int,
    *,
    boost: float = _NEUROGENESIS_BOOST,
    maturation_hours: float = 48.0,
) -> list[float]:
    """Compute dimension-specific weights for temporal pattern separation.

    Simulates adult neurogenesis: new "neurons" are hyperexcitable initially
    and gradually mature. Recent memories get boosted on a rotating subset
    of dimensions (temporal hash), creating natural temporal clustering.

    Args:
        hours_since_creation: Age of the memory in hours.
        embedding_dim: Dimensionality of embeddings.
        boost: How much extra weight new dimensions get.
        maturation_hours: How long until neurogenesis boost fades.

    Returns:
        Per-dimension weight vector (length = embedding_dim).
    """
    boost_magnitude = _compute_boost_magnitude(
        hours_since_creation,
        maturation_hours,
        boost,
    )
    weights = [1.0] * embedding_dim
    _apply_dimension_boosts(weights, hours_since_creation, boost_magnitude)
    return weights


def apply_temporal_weights(
    embedding: list[float],
    weights: list[float],
) -> list[float]:
    """Apply temporal separation weights to an embedding.

    Element-wise multiplication followed by renormalization.

    Returns:
        Temporally-weighted embedding (unit norm).
    """
    if len(embedding) != len(weights):
        return list(embedding)

    weighted = [e * w for e, w in zip(embedding, weights)]
    weighted_norm = norm(weighted)
    if weighted_norm > 1e-10:
        weighted = scale(weighted, 1.0 / weighted_norm)
    return weighted


# ── Separation Metrics ────────────────────────────────────────────────────


def compute_separation_index(
    original_embedding: list[float],
    separated_embedding: list[float],
) -> float:
    """Compute how much an embedding was changed by pattern separation.

    Returns 0.0 if unchanged, approaches 1.0 if completely orthogonalized.
    """
    sim = cosine_similarity(original_embedding, separated_embedding)
    return max(0.0, 1.0 - sim)


def compute_interference_score(
    embedding: list[float],
    neighbor_embeddings: list[list[float]],
    *,
    threshold: float = _SEPARATION_THRESHOLD,
) -> float:
    """Compute how much interference pressure a memory faces.

    Returns average similarity to neighbors above threshold, weighted
    by how far above threshold each neighbor is. Score of 0.0 means
    no interference pressure.
    """
    if not neighbor_embeddings:
        return 0.0

    excess_similarities = []
    for neighbor in neighbor_embeddings:
        sim = cosine_similarity(embedding, neighbor)
        if sim > threshold:
            excess_similarities.append(sim - threshold)

    if not excess_similarities:
        return 0.0

    avg_excess = sum(excess_similarities) / len(neighbor_embeddings)
    return min(1.0, avg_excess / (1.0 - threshold))
