"""Interference management — orthogonalization, retrieval suppression, and domain metrics.

Memory interference is the primary cause of forgetting in both biological and
artificial systems. Detection helpers live in interference_detection.py;
this module provides resolution (orthogonalization), retrieval suppression,
domain pressure metrics, and re-exports all public symbols.

Computational model:
    Norman KA, Newman EL, Detre GJ (2007) A neural network model of
    retrieval-induced forgetting. Psychological Review 114:887-953.

    The full Norman et al. model uses a leaky competing accumulator (LCA)
    with oscillating inhibition:

        da_i/dt = -a_i/tau + sum_j(w_ij * a_j) - g * sum_j(a_j) + input_i

    where g oscillates between g_high (strong lateral inhibition, only the
    strongest pattern survives) and g_low (weak inhibition, moderate
    competitors remain active). Learning uses contrastive Hebbian:

        delta_w = eta * (a_plus * a_plus - a_minus * a_minus)

    where a_plus/a_minus are activations at g_low/g_high respectively.

    Our implementation simplifies the LCA to single-step lateral inhibition
    and projection-based orthogonalization, which captures the core insight
    (strong competitors suppress weak ones; similar representations are
    separated during offline processing) without the full oscillatory
    dynamics. This is appropriate for a memory system operating at
    hours/days timescale rather than the millisecond timescale of the
    neural model.

Additional references:
    Anderson MC, Neely JH (1996) Interference and inhibition in memory
    retrieval. In: Memory (Bjork EL, Bjork RA, eds), pp 237-313.
    Academic Press. — Classic behavioral framework for retrieval-induced
    forgetting.

    Wixted JT (2004) The psychology and neuroscience of forgetting.
    Annual Review of Psychology 55:235-269. — Review article providing
    context on interference vs. decay debate. No computational model;
    cited for conceptual framing only.

    Yassa MA, Stark CEL (2011) Pattern separation in the hippocampus.
    Trends in Neurosciences 34:515-525. — Biological basis for
    orthogonalization of similar memory representations in dentate gyrus.

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
# All constants below are hand-tuned for this system's operating regime
# (hours/days timescale, 384-dim embeddings). They are not derived from
# Norman et al. 2007's parameters (which target ms-timescale neural dynamics).

# Rate at which each orthogonalization step removes the interfering
# projection component. 0.15 yields ~3-6 sleep cycles to fully separate
# two memories at sim > 0.7. Hand-tuned; no direct biological equivalent.
_ORTHOGONALIZATION_RATE = 0.15

# Floor similarity — orthogonalization stops here to preserve meaningful
# semantic overlap. Hand-tuned to prevent over-separation.
_MIN_ORTHOGONAL_SIMILARITY = 0.2

# Lateral inhibition strength for retrieval suppression.
# Simplified from Norman et al. 2007's oscillating g parameter.
# In the full model, g oscillates between ~0.4 (g_high) and ~0.1 (g_low).
# Our fixed 0.3 approximates the time-averaged effect. Hand-tuned.
_RETRIEVAL_SUPPRESSION = 0.3

# Cosine similarity threshold above which two memories are considered
# to be interfering. Hand-tuned; corresponds roughly to the point where
# pattern separation mechanisms would engage in hippocampus (Yassa & Stark 2011).
_INTERFERENCE_THRESHOLD = 0.7


# ── Orthogonalization Helpers ─────────────────────────────────────────────


def _project_away(
    vec: list[float],
    basis: list[float],
    rate: float,
) -> list[float]:
    """Remove a fraction of vec's projection onto basis.

    Implements a simplified version of the sleep-dependent
    orthogonalization described in Yassa & Stark 2011. Each call
    removes rate * 0.5 of the shared component, modeling one
    consolidation cycle.
    """
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

    Models the offline orthogonalization component of interference
    resolution. In Norman et al. 2007, competing representations are
    separated via contrastive Hebbian learning during sleep-like replay.
    We simplify this to symmetric projection removal: each embedding
    has a fraction of its shared component with the other subtracted.

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

    Simplified lateral inhibition consistent with Norman et al. 2007.
    In the full LCA model, units with higher activation suppress units
    with lower activation through the global inhibition term
    -g * sum_j(a_j). Our simplification: only competitors with scores
    higher than the target contribute suppression, proportional to their
    score advantage. This captures the key prediction of the model —
    stronger competitors suppress weaker ones — without requiring
    iterative settling dynamics.

    The suppression_factor parameter approximates the time-averaged
    effect of oscillating g between g_high and g_low. Hand-tuned.

    Args:
        target_score: Retrieval score of the memory being evaluated.
        competitor_scores: Retrieval scores of competing (similar) memories.
        suppression_factor: Lateral inhibition strength (hand-tuned).

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
    """Classify interference pressure level from average score.

    Thresholds are hand-tuned based on observed domain statistics.
    No direct mapping to Norman et al. 2007 parameters.
    """
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
        threshold: Similarity threshold for interference (hand-tuned).
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
