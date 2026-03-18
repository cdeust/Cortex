"""Dense vector math utilities for behavioral activation spaces.

Thin wrappers around numpy. All functions handle empty arrays gracefully
and return 0 for degenerate cases (empty vectors, zero norms).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def dot(a: list[float] | NDArray, b: list[float] | NDArray) -> float:
    """Dot product of two dense vectors. Uses shorter length if unequal."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return float(np.dot(a[:n], b[:n]))


def norm(v: list[float] | NDArray) -> float:
    """Euclidean norm (L2) of a dense vector."""
    v = np.asarray(v, dtype=float)
    if len(v) == 0:
        return 0.0
    return float(np.linalg.norm(v))


def normalize(v: list[float] | NDArray) -> list[float]:
    """Return a unit vector in the same direction. Zero vector if norm is 0."""
    v = np.asarray(v, dtype=float)
    n = norm(v)
    if n == 0:
        return [0.0] * len(v)
    return (v / n).tolist()


def cosine_similarity(a: list[float] | NDArray, b: list[float] | NDArray) -> float:
    """Cosine similarity. Returns 0 if either has zero norm."""
    na = norm(a)
    nb = norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return dot(a, b) / (na * nb)


def _pad_to_same_length(a: NDArray, b: NDArray) -> tuple[NDArray, NDArray]:
    """Pad shorter array with zeros to match longer."""
    if len(a) == len(b):
        return a, b
    n = max(len(a), len(b))
    pa = np.zeros(n)
    pb = np.zeros(n)
    pa[: len(a)] = a
    pb[: len(b)] = b
    return pa, pb


def add(a: list[float] | NDArray, b: list[float] | NDArray) -> list[float]:
    """Element-wise addition, padding shorter vector with zeros."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = _pad_to_same_length(a, b)
    return (a + b).tolist()


def subtract(a: list[float] | NDArray, b: list[float] | NDArray) -> list[float]:
    """Element-wise subtraction: a - b, padding shorter vector with zeros."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = _pad_to_same_length(a, b)
    return (a - b).tolist()


def scale(v: list[float] | NDArray, s: float) -> list[float]:
    """Scalar multiplication."""
    v = np.asarray(v, dtype=float)
    return (v * s).tolist()


def project(a: list[float] | NDArray, b: list[float] | NDArray) -> list[float]:
    """Project vector a onto vector b. Returns zero if b has zero norm."""
    b_arr = np.asarray(b, dtype=float)
    nb2 = dot(b, b)
    if nb2 == 0:
        return [0.0] * len(b_arr)
    scalar = dot(a, b) / nb2
    return scale(b, scalar)


def clamp(v: list[float] | NDArray, lo: float, hi: float) -> list[float]:
    """Clamp each element to [lo, hi]."""
    v = np.asarray(v, dtype=float)
    return np.clip(v, lo, hi).tolist()


def zeros(dim: int) -> list[float]:
    """Create a zero vector of given dimension."""
    return [0.0] * dim
