"""Sparse vector operations for behavioral feature activations.

Sparse vectors represented as dict[str, float] (replacing JS Map<string, number>).
Keys are dimension names, values are activation strengths.
All operations skip/remove zero entries.
"""

from __future__ import annotations

import math


def sparse_dot(a: dict[str, float], b: dict[str, float]) -> float:
    """Dot product of two sparse vectors."""
    smaller, larger = (a, b) if len(a) <= len(b) else (b, a)
    total = 0.0
    for key, val in smaller.items():
        if key in larger:
            total += val * larger[key]
    return total


def sparse_norm(v: dict[str, float]) -> float:
    """Euclidean norm of a sparse vector."""
    return math.sqrt(sum(val * val for val in v.values()))


def sparse_add(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    """Add two sparse vectors. Removes entries that sum to zero."""
    result = dict(a)
    for key, val in b.items():
        s = result.get(key, 0.0) + val
        if s == 0:
            result.pop(key, None)
        else:
            result[key] = s
    return result


def sparse_scale(v: dict[str, float], s: float) -> dict[str, float]:
    """Scale a sparse vector by a scalar."""
    if s == 0:
        return {}
    return {key: val * s for key, val in v.items()}


def sparse_top_k(v: dict[str, float], k: int) -> dict[str, float]:
    """Return the top-K entries by absolute value."""
    entries = sorted(v.items(), key=lambda x: abs(x[1]), reverse=True)
    return dict(entries[:k])


def sparse_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    na = sparse_norm(a)
    nb = sparse_norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return sparse_dot(a, b) / (na * nb)


def dense_to_sparse(
    dense: list[float], labels: list[str], threshold: float = 1e-10
) -> dict[str, float]:
    """Convert a dense vector to sparse, dropping entries below threshold."""
    result: dict[str, float] = {}
    for i in range(min(len(dense), len(labels))):
        if abs(dense[i]) > threshold:
            result[labels[i]] = dense[i]
    return result


def sparse_to_dense(sparse: dict[str, float], labels: list[str]) -> list[float]:
    """Convert a sparse vector to dense using ordered dimension names."""
    return [sparse.get(label, 0.0) for label in labels]
