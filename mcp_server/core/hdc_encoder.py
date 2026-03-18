"""Hyperdimensional Computing (HDC) encoder for structured query encoding.

Implements the bind/bundle/permute algebra over dense bipolar vectors (+1/-1).
Used as retrieval signal 5 in the WRRF fusion pipeline.

Key operations:
  - bind  (⊗) : element-wise multiply — encodes associations  (A AND B)
  - bundle(⊕) : element-wise sum + sign  — encodes superposition (A OR B)
  - permute(ρ) : circular left-shift by n  — encodes sequence/order

Usage in recall:
  1. Encode query as HDC vector by bundling word-hash vectors
  2. Encode each memory's content the same way (on-the-fly)
  3. HDC similarity = dot(query_hdc, memory_hdc) / dim  (ranges -1 to +1)
  4. Use as an additional retrieval signal alongside vector/FTS/heat/Hopfield

No I/O — pure numpy operations.
"""

from __future__ import annotations

import hashlib

import numpy as np

# Default HDC dimensionality — large dim reduces false positives
HDC_DIM = 1024

# Random-projection seed for reproducibility across processes
_SEED = 0xDEADBEEF

# ── Atom generation ───────────────────────────────────────────────────────


def _word_to_hdc(word: str, dim: int = HDC_DIM) -> np.ndarray:
    """Map a word to a deterministic bipolar (+1/-1) hypervector.

    Uses double-hashing to fill the vector uniformly. This is a
    fixed (not trained) mapping — reproducible across processes.

    Args:
        word: The word/token to encode.
        dim: Hypervector dimensionality.
    """
    rng = np.random.default_rng(
        seed=int(hashlib.sha256(word.lower().encode()).hexdigest(), 16) % (2**32)
    )
    bits = rng.integers(0, 2, size=dim, dtype=np.int8)
    return np.where(bits == 0, -1, 1).astype(np.float32)


# ── HDC algebra ───────────────────────────────────────────────────────────


def bind(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Bind two hypervectors via element-wise multiplication.

    Result encodes the association (A AND B).
    bind(a, a) = identity; bind is invertible: unbind(bind(a, b), a) = b.
    """
    return a * b


def bundle(vectors: list[np.ndarray]) -> np.ndarray:
    """Bundle a list of hypervectors via element-wise sum + sign thresholding.

    Result encodes the superposition (A OR B OR ...).
    Similar to the original vectors but not identical to any single one.

    Ties (sum == 0) broken by a fixed tiebreak vector seeded from dim.
    """
    if not vectors:
        raise ValueError("bundle requires at least one vector")
    if len(vectors) == 1:
        return vectors[0].copy()

    stacked = np.stack(vectors, axis=0)  # shape (N, dim)
    summed = stacked.sum(axis=0)  # shape (dim,)

    # Break ties deterministically
    dim = summed.shape[0]
    rng = np.random.default_rng(seed=dim ^ _SEED)
    tiebreak = rng.integers(0, 2, size=dim, dtype=np.int8)
    tiebreak = np.where(tiebreak == 0, -1, 1).astype(np.float32)

    result = np.sign(summed)
    result = np.where(result == 0, tiebreak, result).astype(np.float32)
    return result


def permute(v: np.ndarray, n: int = 1) -> np.ndarray:
    """Permute a hypervector by circular left-shift of n positions.

    Encodes sequence position / temporal order.
    permute(v, 0) = v; permute(permute(v, 1), -1) = v.
    """
    return np.roll(v, -n)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine-like similarity for bipolar vectors.

    For unit-length bipolar vectors: similarity = dot(a, b) / dim.
    Returns value in [-1.0, +1.0]. Threshold for "similar" ≈ 0.1.
    """
    dot = float(np.dot(a, b))
    dim = len(a)
    return dot / dim if dim > 0 else 0.0


# ── Text encoding ─────────────────────────────────────────────────────────


_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "it",
        "in",
        "on",
        "at",
        "of",
        "to",
        "and",
        "or",
        "but",
        "for",
        "not",
        "with",
        "by",
        "as",
        "be",
        "was",
        "are",
        "were",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "this",
        "that",
        "these",
        "those",
        "from",
        "into",
        "about",
        "up",
    }
)


def encode_text(text: str, dim: int = HDC_DIM, use_bigrams: bool = True) -> np.ndarray:
    """Encode a text string as a HDC hypervector.

    Strategy:
      1. Tokenize into words, filter stopwords
      2. Bundle word atoms: Σ word_hdc(w)
      3. If use_bigrams: also bind adjacent word pairs to capture context
         e.g. bind(word_hdc("memory"), word_hdc("decay"))
      4. Bundle all together and normalize to bipolar

    Args:
        text: Input text to encode.
        dim: Hypervector dimensionality.
        use_bigrams: Whether to include bigram-bound vectors.
    """
    words = [w.lower().strip(".,!?;:()[]{}\"'`") for w in text.split() if len(w) > 1]
    words = [w for w in words if w not in _STOP_WORDS]

    if not words:
        # Return a zero-filled array as neutral encoding
        return np.zeros(dim, dtype=np.float32)

    vecs: list[np.ndarray] = []

    # Unigram atoms
    for w in words:
        vecs.append(_word_to_hdc(w, dim))

    # Bigram bound pairs (encode context/association)
    if use_bigrams and len(words) >= 2:
        for i in range(len(words) - 1):
            bound = bind(_word_to_hdc(words[i], dim), _word_to_hdc(words[i + 1], dim))
            vecs.append(bound)

    return bundle(vecs)


def encode_with_position(tokens: list[str], dim: int = HDC_DIM) -> np.ndarray:
    """Encode a token sequence preserving order via permutation.

    pos_i encodes token at position i by permuting its atom i times.
    Useful for encoding structured sequences (import paths, function signatures).
    """
    if not tokens:
        return np.zeros(dim, dtype=np.float32)

    vecs = [permute(_word_to_hdc(t, dim), i) for i, t in enumerate(tokens)]
    return bundle(vecs)


# ── Retrieval signal ──────────────────────────────────────────────────────


def compute_hdc_scores(
    query_text: str,
    memory_contents: list[tuple[int, str]],
    dim: int = HDC_DIM,
    threshold: float = 0.05,
) -> list[tuple[int, float]]:
    """Compute HDC retrieval scores for a query against a list of memories.

    Args:
        query_text: Raw query string.
        memory_contents: List of (memory_id, content) pairs.
        dim: HDC dimensionality.
        threshold: Minimum similarity to include in results.

    Returns:
        List of (memory_id, similarity_score) sorted descending.
        Scores are in [-1, 1] but practically [0, 1] for relevant results.
    """
    if not memory_contents:
        return []

    query_hdc = encode_text(query_text, dim)

    results: list[tuple[int, float]] = []
    for mem_id, content in memory_contents:
        mem_hdc = encode_text(content, dim)
        sim = similarity(query_hdc, mem_hdc)
        if sim >= threshold:
            results.append((mem_id, sim))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
