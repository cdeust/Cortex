"""Set similarity metrics for keyword and domain comparison.

Jaccard similarity coefficient: |A & B| / |A | B|. Returns 0 for empty sets.
"""

from __future__ import annotations


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity between two sets.

    Returns a value in [0, 1]. Returns 0 for two empty sets.
    """
    if not set_a and not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0
