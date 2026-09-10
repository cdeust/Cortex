"""Deterministic, download-free algorithmic text embeddings.

source: ADR-0643"""

from __future__ import annotations

import hashlib
import math
import struct

import numpy as np

from mcp_server.shared.code_tokenize import split_identifier

# source: ADR-0643


_NONZERO_PER_TOKEN = 8

# source: ADR-0643
_WINDOW = 5

# source: ADR-0643


_MAX_OCCUR = 512


def _token_seed(token: str) -> int:
    """Deterministic 64-bit seed for a token (platform-independent).

    source: ADR-0643"""
    return int.from_bytes(
        hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big"
    )


def index_vector(token: str, dim: int) -> np.ndarray:
    """Return the sparse ternary Random-Indexing vector for ``token``.

    precondition: ``token`` is a non-empty str; ``dim`` > 0.
    postcondition: returns a float32 array of shape ``(dim,)`` with at most
    ``_NONZERO_PER_TOKEN`` non-zero entries in {-1, +1}; deterministic in
    ``(token, dim)``.

    source: ADR-0643"""
    vec = np.zeros(dim, dtype=np.float32)
    seed = _token_seed(token)
    for i in range(_NONZERO_PER_TOKEN):
        h = int.from_bytes(
            hashlib.blake2b(
                struct.pack("<q", i), key=struct.pack("<Q", seed), digest_size=8
            ).digest(),
            "big",
        )
        pos = h % dim
        vec[pos] += 1.0 if (h & 1) else -1.0
    return vec


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase sub-tokens (same rule as the FTS tokenizer).

    postcondition: identifiers are decomposed (``normalizePaymentAmount`` →
    ``normalize, payment, amount``) so the embedding vocabulary and the FTS
    vocabulary agree; ordering is preserved for the co-occurrence window.
    """
    tokens: list[str] = []
    for word in text.replace("\n", " ").split():
        tokens.extend(split_identifier(word))
    return tokens


def _tf_weights(tokens: list[str]) -> dict[str, float]:
    """Sublinear term-frequency weight per distinct token: ``1 + log(tf)``.

    source: ADR-0643"""
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return {t: 1.0 + math.log(c) for t, c in counts.items()}


def _accumulate_window(
    acc: np.ndarray,
    tokens: list[str],
    cache: dict[str, np.ndarray],
    center: int,
    weight: float,
) -> None:
    """Add the distance-weighted (``1/d``) index vectors of ``center``'s
    neighbours within ``±_WINDOW`` into ``acc`` in place.

    precondition: ``acc`` is the caller's live accumulator (documented owner:
    ``embed_text``); ``0 <= center < len(tokens)``.
    postcondition: ``acc`` is incremented by ``sum_j (weight/|j-center|) *
    cache[tokens[j]]`` over the window, excluding ``j == center``.
    """
    n = len(tokens)
    lo = max(0, center - _WINDOW)
    hi = min(n, center + _WINDOW + 1)
    for j in range(lo, hi):
        if j != center:
            acc += (weight / abs(j - center)) * cache[tokens[j]]


def _first_order_pass(
    acc: np.ndarray,
    tokens: list[str],
    tf: dict[str, float],
    cache: dict[str, np.ndarray],
) -> None:
    """Add each token's tf-weighted index vector into ``acc`` in place, once per
    occurrence.

    precondition: ``acc`` is the caller's live accumulator (owner:
    ``embed_text``); ``tf`` and ``cache`` are keyed by every distinct token.
    postcondition: ``acc`` is incremented by ``sum_i tf[tokens[i]] *
    cache[tokens[i]]`` over ALL positions — never subsampled (CBM keeps a
    token's own source vector intact; semantic.c:930 sem_target_init_from_src).
    """
    for tok in tokens:
        acc += tf[tok] * cache[tok]


def _cooccurrence_pass(
    acc: np.ndarray,
    tokens: list[str],
    tf: dict[str, float],
    cache: dict[str, np.ndarray],
) -> None:
    """Add distance-weighted co-occurrence enrichment into ``acc`` in place,
    with CBM frequent-token subsampling.

    precondition: acc is embed_text's live accumulator; tf and cache are
    keyed by every distinct token.
    postcondition: occurrence positions contribute a windowed sum. Tokens
    exceeding _MAX_OCCUR use strided position samples; the caller's
    first-order contribution is unchanged.
    source: ADR-0643"""
    positions: dict[str, list[int]] = {}
    for i, tok in enumerate(tokens):
        positions.setdefault(tok, []).append(i)
    for tok, occ in positions.items():
        step = max(1, len(occ) // _MAX_OCCUR)
        weight = tf[tok]
        for i in occ[::step]:
            _accumulate_window(acc, tokens, cache, i, weight)


def embed_text(text: str, dim: int) -> np.ndarray:
    """Encode ``text`` into a deterministic, L2-normalized dense vector.

    precondition: ``text`` is a str (may be empty); ``dim`` > 0.
    postcondition: returns a float32 array of shape ``(dim,)``; L2 norm is 1.0
    when ``text`` has at least one token, else the zero vector; the result is
    deterministic in ``(text, dim)`` and lies in the SAME vector-space contract
    (dimension) as the neural encoder, though NOT the same geometry — the two
    spaces are incomparable and callers must not cross-rank them.
    invariant: every token contributes exactly one complete first-order term;
    the co-occurrence pass is strided only for a token whose within-document
    occurrence count exceeds ``_MAX_OCCUR`` (CBM ``cooccur_sparse_one_target``).
    """
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)

    tf = _tf_weights(tokens)
    # Cache each distinct token's index vector once — an O(unique) not
    # O(occurrences) build.
    cache: dict[str, np.ndarray] = {t: index_vector(t, dim) for t in tf}

    acc = np.zeros(dim, dtype=np.float32)
    _first_order_pass(acc, tokens, tf, cache)
    _cooccurrence_pass(acc, tokens, tf, cache)

    norm = float(np.linalg.norm(acc))
    if norm > 0.0:
        acc /= norm
    return acc.astype(np.float32)
