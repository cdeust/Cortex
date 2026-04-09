"""Submodular coverage selection for Phase 1 own-stage retrieval.

Replaces "top-k by score" with greedy submodular coverage: each new
chunk is picked to maximize marginal information gain given what has
already been selected. Directly addresses the "near-duplicate top-k"
failure mode observed at BEAM-10M scale, where the 5 highest-scored
chunks are often substrings of each other.

**Paper backing**:
  Krause & Guestrin, "Near-Optimal Sensor Placements in Gaussian
  Processes", JMLR 9:235-284 (2008). Proves that for a monotone
  submodular set function f, the greedy algorithm returns S_k with
  f(S_k) >= (1 - 1/e) * f(S*_k) ≈ 0.63 * optimal. Also introduces
  the lazy greedy acceleration (Minoux 1978) that makes selection
  nearly O(n log n) instead of O(n^2).

**Applied here**: marginal relevance = score - λ * max_similarity(c, S)
where similarity is cosine over embeddings. This is the Carbonell &
Goldstein MMR (1998) objective, which is submodular when λ < 1.
"""
from __future__ import annotations

import numpy as np

from mcp_server.core.context_assembly.budget import estimate_tokens


def submodular_select(
    candidates: list[dict],
    *,
    token_budget: int | None,
    diversity_lambda: float = 0.5,
    max_chunks: int = 5,
    score_key: str = "score",
    content_key: str = "content",
    embedding_key: str = "embedding",
) -> list[dict]:
    """Greedy submodular selection, optionally within a token budget.

    Selection is driven by `max_chunks` first. `token_budget` is an
    OPTIONAL soft upper bound — when None, the function always picks
    `max_chunks` items regardless of total tokens. This matters because
    the same primitive is used in two very different contexts:

      1. **Retrieval ranking evaluation**: we want exactly max_chunks
         items so retrieval hit ranks are well-defined. The text size
         is irrelevant here.
      2. **Prompt assembly for an LLM reader**: we want the tightest
         set of items that fits the reader's context window. Here
         token_budget matters and max_chunks is a hint.

    When both max_chunks and token_budget are set, the function stops
    at whichever is reached first. When token_budget is None, only
    max_chunks applies.

    Args:
        candidates: list of candidate dicts, pre-scored by the retriever.
        token_budget: soft upper bound on total tokens. None = ignore.
        diversity_lambda: MMR diversity weight in [0, 1]. 0 = pure
            relevance (top-k), 1 = pure diversity.
        max_chunks: hard cap on number of selected chunks.
        score_key / content_key / embedding_key: field names.
    """
    if not candidates:
        return []

    # Normalize candidates to embeddings (None for candidates without one)
    embeddings: list[np.ndarray | None] = []
    for c in candidates:
        raw = c.get(embedding_key)
        if raw is None:
            embeddings.append(None)
        elif isinstance(raw, (bytes, bytearray)):
            embeddings.append(np.frombuffer(raw, dtype=np.float32))
        else:
            embeddings.append(np.asarray(raw, dtype=np.float32))

    scores = [float(c.get(score_key, 0.0)) for c in candidates]
    token_counts = [estimate_tokens(c.get(content_key, "")) for c in candidates]

    selected: list[int] = []
    selected_embs: list[np.ndarray] = []
    used_tokens = 0

    while len(selected) < max_chunks:
        best_i = -1
        best_gain = -float("inf")
        for i in range(len(candidates)):
            if i in selected:
                continue
            if (
                token_budget is not None
                and used_tokens + token_counts[i] > token_budget
            ):
                continue

            # Marginal relevance = score - λ * max sim to already-selected
            if not selected_embs or embeddings[i] is None:
                penalty = 0.0
            else:
                emb = embeddings[i]
                sims = [
                    float(np.dot(emb, s) / (np.linalg.norm(emb) * np.linalg.norm(s) + 1e-8))
                    for s in selected_embs
                    if s is not None
                ]
                penalty = max(sims) if sims else 0.0
            gain = scores[i] - diversity_lambda * penalty

            if gain > best_gain:
                best_gain = gain
                best_i = i

        if best_i < 0:
            break  # No candidate fits budget
        selected.append(best_i)
        if embeddings[best_i] is not None:
            selected_embs.append(embeddings[best_i])
        used_tokens += token_counts[best_i]

    # Return in original ranking order for readability
    selected_sorted = sorted(selected)
    return [candidates[i] for i in selected_sorted]
