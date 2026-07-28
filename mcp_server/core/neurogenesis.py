"""Temporal-context dimension weighting and separation metrics.

This module implements a temporal-context encoding heuristic: a rotating
hash-selected subset of fixed embedding dimensions is boosted by a magnitude
that decays with memory age, so recent memories cluster on shared dimensions.
It does NOT implement dentate-gyrus pattern separation. The "neurogenesis"
framing is a loose biological MOTIVATION, not a faithful model — the cited
papers below inspire the concept (young, broadly-tuned units carry temporal/
contextual signal that fades as they mature) but prescribe no weight, decay,
or threshold formula. All numeric constants here are engineering defaults
(see per-constant comments), not paper-derived values.

Motivating references (concept only, NOT a source for any constant):
    Aimone JB, Deng W, Gage FH (2011) Resolving new memories: a critical look
        at the dentate gyrus, adult neurogenesis, and pattern separation.
        Neuron 70:589-596. A review proposing the "memory resolution"
        hypothesis; it gives no computational weight/threshold formula.
    Cognitive Neurodynamics (2025) Dynamic impact of adult neurogenesis on
        pattern separation in the DG neural network. (network simulation;
        not a prescription for embedding-dimension weights)

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

# Numerical floor below which a vector norm is treated as zero.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_NORM_EPSILON = 1e-10

# Extra weight applied to the "young" (recently-boosted) dimension subset at
# zero age. No paper prescribes this magnitude — Aimone 2011 is a review with
# no formula.
# source: engineering default; calibration pending
_NEUROGENESIS_BOOST = 0.3

# Cosine-similarity threshold above which a neighbor counts as interference
# pressure. Mirrors the same 0.75 in separation_core.py, which is likewise an
# empirically-tuned engineering choice for 384-dim dense embeddings (the DG
# sourced value there is _SPARSITY_TARGET=0.04 sparsity from Leutgeb 2007 —
# a sparsity fraction, NOT a cosine threshold, so there is nothing to defer to).
# source: engineering default; calibration pending
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
    # 6.0 = hours per temporal bucket (memories within the same 6h window share
    #   the same boosted dimension subset); 7 = stride that rotates the boosted
    #   window across buckets (coprime-ish with typical dims to spread coverage);
    #   0.1 = fraction of dimensions boosted per bucket (~10%). None of these are
    #   paper-derived; they are hand-picked knobs controlling temporal-cluster
    #   granularity, and have not been calibrated against retrieval benchmarks.
    # source: engineering default; calibration pending
    _hours_per_bucket = 6.0
    _bucket_stride = 7
    _boosted_fraction = 0.1
    time_bucket = int(hours_since_creation / _hours_per_bucket)
    boosted_start = (time_bucket * _bucket_stride) % embedding_dim
    boosted_count = max(1, int(embedding_dim * _boosted_fraction))

    for i in range(boosted_count):
        dim_idx = (boosted_start + i) % embedding_dim
        weights[dim_idx] = 1.0 + boost_magnitude


def compute_temporal_separation_weights(
    hours_since_creation: float,
    embedding_dim: int,
    *,
    boost: float = _NEUROGENESIS_BOOST,
    # Exponential time-constant (hours) over which the boost decays via
    # 1 - exp(-t/maturation_hours). 48h is a hand-chosen "recent memory" window
    # at this system's hours/days timescale; Aimone 2011 discusses a weeks-long
    # biological maturation window but gives no time-constant to port here.
    # source: engineering default; calibration pending
    maturation_hours: float = 48.0,
) -> list[float]:
    """Compute dimension-specific weights for temporal-context encoding.

    A rotating hash-selected subset of dimensions is boosted by a magnitude
    that decays with memory age, so recent memories cluster on shared
    dimensions. This is a temporal-context heuristic inspired by — not an
    implementation of — Aimone's pattern-separation hypothesis (see module
    docstring); all constants are engineering defaults.

    Args:
        hours_since_creation: Age of the memory in hours.
        embedding_dim: Dimensionality of embeddings.
        boost: Extra weight applied to the boosted dimension subset at age 0.
        maturation_hours: Time-constant over which the boost decays.

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

    # strict=True is safe here — the explicit length check above guarantees
    # equality. Defensive: if a future edit removes the guard, strict will
    # surface the regression as an exception instead of silently weighting
    # only the shorter prefix.
    weighted = [e * w for e, w in zip(embedding, weights, strict=True)]
    weighted_norm = norm(weighted)
    if weighted_norm > _NORM_EPSILON:
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
