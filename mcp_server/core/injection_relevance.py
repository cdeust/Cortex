"""Semantic eligibility for automatic context injection (issue #706).

The cross-encoder cannot decide whether a paraphrased memory is relevant: on
the hosted fixture its raw score for 12 of 30 expected passages is at most
4e-5, under the unrelated negative controls' best passages. Embedding cosine,
the signal explicit recall already fuses, separates the same pairs.
"""

from __future__ import annotations

import numpy as np

# source: hosted parity artifact, run 40794598785 (fixture sha256 8eeacbd7…,
# all-MiniLM-L6-v2 @ 1110a243): lowest expected-passage cosine 0.235, highest
# negative-control passage cosine 0.152; the floor sits inside that gap.
# Calibrated on 30 positive and 3 negative prompts, not a global constant.
INJECTION_SIMILARITY_FLOOR = 0.19


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    """Cosine similarity; a zero-norm vector is unrelated to everything."""
    norm = float(np.linalg.norm(left) * np.linalg.norm(right))
    if norm == 0.0:
        return 0.0
    return float(np.dot(left, right) / norm)


def relevant_by_similarity(
    query: np.ndarray,
    vectors: dict[int, np.ndarray],
    floor: float = INJECTION_SIMILARITY_FLOOR,
) -> list[int]:
    """Ids at or above ``floor``, most similar first (ties: lower id first).

    Precondition: every vector has the query's dimension; others are skipped.
    Postcondition: an empty list means the hook abstains.
    """
    scored = [
        (cosine(query, vector), mid)
        for mid, vector in vectors.items()
        if vector.shape == query.shape
    ]
    eligible = [(score, mid) for score, mid in scored if score >= floor]
    return [mid for _, mid in sorted(eligible, key=lambda pair: (-pair[0], pair[1]))]


__all__ = ["INJECTION_SIMILARITY_FLOOR", "cosine", "relevant_by_similarity"]
