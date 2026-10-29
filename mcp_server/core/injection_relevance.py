"""Semantic eligibility for automatic context injection (issue #706).

The cross-encoder cannot decide whether a paraphrased memory is relevant: on
the hosted fixture its raw score for 12 of 30 expected passages is at most
4e-5, under the unrelated negative controls' best passages. Embedding cosine,
the signal explicit recall already fuses, separates the same pairs. The
similarities are computed by the infrastructure encoder; this module only
decides.
"""

from __future__ import annotations

from collections.abc import Mapping

# source: hosted parity artifact, run 40794598785 (fixture sha256 8eeacbd7…,
# all-MiniLM-L6-v2 @ 1110a243): lowest expected-passage cosine 0.235, highest
# negative-control passage cosine 0.152; the floor sits inside that gap.
# Calibrated on 30 positive and 3 negative prompts, not a global constant.
INJECTION_SIMILARITY_FLOOR = 0.19


def relevant_by_similarity(
    similarities: Mapping[int, float],
    floor: float = INJECTION_SIMILARITY_FLOOR,
) -> list[int]:
    """Ids at or above ``floor``, most similar first (ties: lower id first).

    Postcondition: an empty list means the hook abstains.
    """
    eligible = [(score, mid) for mid, score in similarities.items() if score >= floor]
    return [mid for _, mid in sorted(eligible, key=lambda pair: (-pair[0], pair[1]))]


__all__ = ["INJECTION_SIMILARITY_FLOOR", "relevant_by_similarity"]
