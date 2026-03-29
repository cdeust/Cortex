"""Modern Hopfield Networks for energy-based associative memory retrieval.

Implements the continuous Hopfield model from Ramsauer et al. (2021),
"Hopfield Networks is All You Need". Retrieval is equivalent to
transformer attention: softmax(beta * X^T * query).

Pure business logic — operates on numpy arrays directly.
Storage access is handled by the caller.

Key capabilities:
  - Dense retrieval via softmax attention over stored patterns
  - Sparse retrieval via sparsemax (Hopfield-Fenchel-Young)
  - Pattern completion via iterative Hopfield dynamics
  - Energy-based novelty detection
"""

from __future__ import annotations

import numpy as np


def _softmax(logits: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    shifted = logits - np.max(logits)
    exp_vals = np.exp(shifted)
    return exp_vals / exp_vals.sum()


def _sparsemax(logits: np.ndarray) -> np.ndarray:
    """Sparsemax: projects logits onto the probability simplex.

    Produces exact zeros for irrelevant entries, unlike softmax.
    Algorithm from Martins & Astudillo (2016).
    """
    n = len(logits)
    if n == 0:
        return logits

    sorted_logits = np.sort(logits)[::-1]
    cumsum = np.cumsum(sorted_logits)
    k_range = np.arange(1, n + 1, dtype=np.float64)
    thresholds = (cumsum - 1.0) / k_range
    support = sorted_logits > thresholds
    k = max(int(np.sum(support)), 1)
    tau = (cumsum[k - 1] - 1.0) / k
    return np.maximum(logits - tau, 0.0)


def _logsumexp(x: np.ndarray) -> float:
    """Numerically stable log-sum-exp."""
    max_x = np.max(x)
    return float(max_x + np.log(np.sum(np.exp(x - max_x))))


def build_pattern_matrix(
    embeddings: list[tuple[int, bytes]],
    embedding_dim: int,
) -> tuple[np.ndarray, list[int]]:
    """Build the N x D pattern matrix from memory embeddings.

    Args:
        embeddings: List of (memory_id, embedding_bytes) pairs.
        embedding_dim: Expected embedding dimensionality.

    Returns:
        (pattern_matrix, pattern_ids) — L2-normalized rows.
    """
    rows = []
    ids = []
    for mem_id, emb_bytes in embeddings:
        vec = np.frombuffer(emb_bytes, dtype=np.float32).copy()
        if len(vec) != embedding_dim:
            continue
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        rows.append(vec)
        ids.append(mem_id)

    if not rows:
        return np.empty((0, 0), dtype=np.float32), []

    return np.stack(rows), ids


def retrieve(
    query_embedding: bytes,
    pattern_matrix: np.ndarray,
    pattern_ids: list[int],
    beta: float = 8.0,
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """Retrieve memories using Modern Hopfield attention.

    Computes: attention = softmax(beta * X * query)
    Returns top_k (memory_id, attention_weight) sorted descending.
    """
    if pattern_matrix.size == 0:
        return []

    query = np.frombuffer(query_embedding, dtype=np.float32).copy()
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm

    logits = beta * (pattern_matrix @ query)
    attention = _softmax(logits)

    top_indices = np.argsort(attention)[::-1][:top_k]
    return [
        (pattern_ids[i], float(attention[i])) for i in top_indices if attention[i] > 0
    ]


def retrieve_sparse(
    query_embedding: bytes,
    pattern_matrix: np.ndarray,
    pattern_ids: list[int],
    beta: float = 8.0,
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """Hopfield-Fenchel-Young retrieval using sparsemax.

    Produces EXACT zeros for irrelevant memories.
    """
    if pattern_matrix.size == 0:
        return []

    query = np.frombuffer(query_embedding, dtype=np.float32).copy()
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm

    logits = beta * (pattern_matrix @ query)
    weights = _sparsemax(logits)

    nonzero = np.nonzero(weights)[0]
    if len(nonzero) == 0:
        return []

    sorted_nz = nonzero[np.argsort(weights[nonzero])[::-1]]
    return [(pattern_ids[i], float(weights[i])) for i in sorted_nz[:top_k]]


def pattern_completion(
    partial_embedding: bytes,
    pattern_matrix: np.ndarray,
    beta: float = 8.0,
    iterations: int = 5,
) -> bytes:
    """Iterative Hopfield dynamics for completing partial/noisy queries.

    For each iteration: xi_new = X^T @ softmax(beta * X @ xi_old)
    Converges to a stored pattern (or blend of nearby patterns).
    """
    xi = np.frombuffer(partial_embedding, dtype=np.float32).copy()
    norm = np.linalg.norm(xi)
    if norm > 0:
        xi = xi / norm

    if pattern_matrix.size == 0:
        return xi.astype(np.float32).tobytes()

    for _ in range(iterations):
        logits = beta * (pattern_matrix @ xi)
        attn = _softmax(logits)
        xi_new = pattern_matrix.T @ attn
        norm = np.linalg.norm(xi_new)
        if norm > 0:
            xi_new = xi_new / norm
        xi = xi_new

    return xi.astype(np.float32).tobytes()


def compute_energy(
    query_embedding: bytes,
    pattern_matrix: np.ndarray,
    beta: float = 8.0,
) -> float:
    """Compute Hopfield energy for a query.

    E(xi, X) = -log(sum exp(beta * x_i^T * xi)) + 0.5 * |xi|^2

    Lower energy = query is well-represented by stored patterns.
    Higher energy = novel/surprising content.
    """
    query = np.frombuffer(query_embedding, dtype=np.float32).copy()
    norm_sq = float(np.dot(query, query))

    if pattern_matrix.size == 0:
        return 0.5 * norm_sq

    norm = np.linalg.norm(query)
    if norm > 0:
        query_normed = query / norm
    else:
        query_normed = query

    logits = beta * (pattern_matrix @ query_normed)
    return -_logsumexp(logits) + 0.5 * norm_sq


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embedding blobs."""
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    dot = float(np.dot(va, vb))
    norm = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if norm == 0:
        return 0.0
    return dot / norm
