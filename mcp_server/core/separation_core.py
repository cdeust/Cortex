"""Pattern separation core — dentate gyrus orthogonalization and sparsification.

Implements the computational analog of hippocampal dentate gyrus (DG) pattern
separation: similar inputs are orthogonalized and sparsified to force
non-overlapping representations.

The biological DG achieves pattern separation through winner-take-all lateral
inhibition among granule cells (beta_INT ~0.9; Myers & Scharfman 2009),
producing extremely sparse population codes (~2-5% active cells). This module
uses Gram-Schmidt projection as a computational proxy — the mathematical effect
(increasing Hamming distance between similar patterns) is equivalent, though the
biological mechanism is competitive inhibition, not linear algebra.

References:
    Leutgeb JK et al. (2007) Pattern separation in the DG and CA3.
        Science 315:961-966
    Yassa MA, Stark CEL (2011) Pattern separation in the hippocampus.
        Trends in Neurosciences 34:515-525
    Rolls ET (2013) The mechanisms for pattern completion and pattern
        separation in the hippocampus. Front Syst Neurosci 7:74
    Myers CE, Scharfman HE (2009) A role for hilar cells in pattern
        separation in the dentate gyrus. Hippocampus 19:321-337

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.shared.linear_algebra import (
    cosine_similarity,
    dot,
    norm,
    scale,
    subtract,
)

# ── Configuration ─────────────────────────────────────────────────────────

# Engineering choice: cosine similarity threshold above which two memories need
# separation. The biological DG uses firing rate overlap, not cosine similarity;
# this threshold was tuned empirically for 384-dim dense embeddings.
_SEPARATION_THRESHOLD = 0.75

# Engineering choice: deduplication boundary. Above this cosine similarity,
# memories are treated as near-duplicates (handled by dedup, not separation).
_IDENTITY_THRESHOLD = 0.95

# Engineering constraint: floor for post-separation similarity with the original
# embedding, preventing orthogonalization from destroying semantic content.
_MIN_POST_SEPARATION_SIMILARITY = 0.3

# DG granule cell activation sparsity: 2-5% of cells active.
# Leutgeb et al. (2007) Science 315:961-966; Rolls (2013) Front Syst Neurosci.
# We use 4% as the midpoint of the published range.
_SPARSITY_TARGET = 0.04


# ── Interference Detection ───────────────────────────────────────────────


def detect_interference_risk(
    new_embedding: list[float],
    existing_embeddings: list[list[float]],
    *,
    threshold: float = _SEPARATION_THRESHOLD,
    identity_threshold: float = _IDENTITY_THRESHOLD,
) -> list[tuple[int, float]]:
    """Detect which existing memories create interference risk for a new memory.

    Returns indices and similarities of memories that are similar enough to
    interfere but not identical (those are duplicates, not interference).

    Returns:
        List of (index, similarity) tuples, sorted by similarity descending.
    """
    risks: list[tuple[int, float]] = []
    for i, existing in enumerate(existing_embeddings):
        sim = cosine_similarity(new_embedding, existing)
        if threshold <= sim < identity_threshold:
            risks.append((i, sim))
    risks.sort(key=lambda x: x[1], reverse=True)
    return risks


# ── Orthogonalization ────────────────────────────────────────────────────


def _project_away_from_single(
    result: list[float],
    interferer: list[float],
    original: list[float],
    strength: float,
    min_similarity: float,
) -> list[float]:
    """Project result away from a single interferer, preserving semantic content.

    Returns the updated result vector, or the original result if the
    projection would violate the minimum similarity constraint.
    """
    interferer_norm = norm(interferer)
    if interferer_norm < 1e-10:
        return result

    projection_coeff = dot(result, interferer) / (interferer_norm**2)
    projection = scale(interferer, projection_coeff * strength)
    candidate = subtract(result, projection)

    candidate_norm = norm(candidate)
    if candidate_norm < 1e-10:
        return result

    candidate = scale(candidate, 1.0 / candidate_norm)

    sim_with_original = cosine_similarity(original, candidate)
    if sim_with_original >= min_similarity:
        return candidate
    return result


def _normalize_result(result: list[float]) -> list[float]:
    """Normalize to unit length if non-degenerate."""
    result_norm = norm(result)
    if result_norm > 1e-10:
        return scale(result, 1.0 / result_norm)
    return result


def orthogonalize_embedding(
    new_embedding: list[float],
    interfering_embeddings: list[list[float]],
    *,
    strength: float = 0.5,
    min_similarity: float = _MIN_POST_SEPARATION_SIMILARITY,
) -> tuple[list[float], float]:
    """Orthogonalize a new embedding away from interfering memories.

    Uses a Gram-Schmidt-like projection: subtract the component of the new
    embedding that lies in the subspace spanned by interfering memories.
    Strength controls how aggressively we separate (0=no change,
    1=full orthogonalization).

    Returns:
        Tuple of (orthogonalized_embedding, separation_index).
        separation_index = 1.0 - cosine_similarity(original, orthogonalized).
    """
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.PATTERN_SEPARATION):
        # No-op: identity, zero separation.
        return list(new_embedding), 0.0
    if not interfering_embeddings:
        return list(new_embedding), 0.0

    result = list(new_embedding)
    dim = len(result)

    for interferer in interfering_embeddings:
        if len(interferer) != dim:
            continue
        result = _project_away_from_single(
            result, interferer, new_embedding, strength, min_similarity
        )

    result = _normalize_result(result)
    separation_index = 1.0 - cosine_similarity(new_embedding, result)
    return result, max(0.0, separation_index)


# ── Sparsification ───────────────────────────────────────────────────────


def apply_sparsification(
    embedding: list[float],
    *,
    sparsity: float = _SPARSITY_TARGET,
) -> list[float]:
    """Apply DG-like sparsification to an embedding.

    Zeroes out the smallest dimensions to achieve target sparsity.
    This simulates the DG's sparse activation pattern where only a few
    percent of granule cells are active.

    Note: this is a lossy operation. The caller should store the original
    embedding for later reference.

    Returns:
        Sparsified embedding (same length, many dimensions zeroed).
    """
    dim = len(embedding)
    k = max(1, int(dim * sparsity))

    indexed = [(abs(v), i) for i, v in enumerate(embedding)]
    indexed.sort(reverse=True)
    keep_indices = {idx for _, idx in indexed[:k]}

    result = [v if i in keep_indices else 0.0 for i, v in enumerate(embedding)]

    result_norm = norm(result)
    if result_norm > 1e-10:
        result = scale(result, 1.0 / result_norm)

    return result
