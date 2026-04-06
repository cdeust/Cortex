"""MMR diversity reranking for summarization queries.

Maximal Marginal Relevance (Carbonell & Goldstein, SIGIR 1998):
iteratively selects documents maximizing relevance to query while
minimizing redundancy with already-selected documents.

Activated only for SUMMARIZATION intent to improve nugget coverage
in BEAM benchmark evaluation.

Pure business logic — no I/O.

Citation:
    Carbonell, J. & Goldstein, J. (1998). "The Use of MMR,
    Diversity-Based Reranking for Reordering Documents and
    Producing Summaries." SIGIR 1998, pp. 335-336.
"""

from __future__ import annotations

import numpy as np


def mmr_rerank(
    candidates: list[dict],
    query_embedding: bytes | None,
    *,
    lambda_param: float = 0.5,
    top_k: int = 10,
) -> list[dict]:
    """Rerank candidates via MMR for diversity.

    MMR score = lambda * sim(d_i, q) - (1-lambda) * max_{d_j in S} sim(d_i, d_j)

    Args:
        candidates: Ranked results with 'embedding' (bytes) and 'score'.
        query_embedding: Query vector as float32 bytes.
        lambda_param: Relevance-diversity tradeoff.
            0.0 = pure diversity, 1.0 = pure relevance.
            Default 0.5 (balanced). Carbonell & Goldstein recommend
            0.3 for summarization, but 0.5 is safer without ablation.
        top_k: Number of results to select.

    Returns:
        Reranked candidates list (length <= top_k).
    """
    if len(candidates) <= 1 or query_embedding is None:
        return candidates[:top_k]

    # Convert embeddings to numpy
    q_vec = _to_numpy(query_embedding)
    if q_vec is None:
        return candidates[:top_k]

    cand_vecs = []
    valid_indices = []
    for i, c in enumerate(candidates):
        v = _to_numpy(c.get("embedding"))
        if v is not None:
            cand_vecs.append(v)
            valid_indices.append(i)

    if not cand_vecs:
        return candidates[:top_k]

    # Pre-compute query similarities
    vecs = np.array(cand_vecs)
    q_sims = _cosine_batch(vecs, q_vec)

    # Greedy MMR selection
    selected_idx: list[int] = []
    remaining = set(range(len(vecs)))

    for _ in range(min(top_k, len(vecs))):
        best_score = -float("inf")
        best_i = -1

        for i in remaining:
            relevance = q_sims[i]

            if selected_idx:
                max_sim = max(_cosine(vecs[i], vecs[j]) for j in selected_idx)
            else:
                max_sim = 0.0

            score = lambda_param * relevance - (1 - lambda_param) * max_sim

            if score > best_score:
                best_score = score
                best_i = i

        if best_i < 0:
            break

        selected_idx.append(best_i)
        remaining.discard(best_i)

    return [candidates[valid_indices[i]] for i in selected_idx]


def _to_numpy(emb: bytes | None) -> np.ndarray | None:
    """Convert float32 bytes to numpy array."""
    if emb is None:
        return None
    if isinstance(emb, np.ndarray):
        return emb
    try:
        return np.frombuffer(emb, dtype=np.float32)
    except (ValueError, TypeError):
        return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


def _cosine_batch(vecs: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row in vecs against query."""
    dots = vecs @ query
    norms = np.linalg.norm(vecs, axis=1) * np.linalg.norm(query)
    norms = np.maximum(norms, 1e-10)
    return dots / norms
