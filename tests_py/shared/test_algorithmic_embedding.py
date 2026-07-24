"""Tests for the deterministic algorithmic embedder (issue #169).

Contract assertions (each must fail on regression):
  - Output dimension equals the requested dim (space contract)
  - Deterministic: same (text, dim) → byte-identical vector
  - L2-normalized for non-empty text; zero vector for empty
  - Semantic ordering: a topically-matching text out-scores an unrelated one
  - camelCase identifiers bridge to their split words (shared tokenizer)
"""

from __future__ import annotations

import numpy as np

from mcp_server.shared.algorithmic_embedding import embed_text, index_vector


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # both already L2-normalized


def test_dimension_contract():
    for dim in (128, 384, 768):
        assert embed_text("some memory text", dim).shape == (dim,)


def test_determinism():
    a = embed_text("normalizePaymentAmount rounds the charge", 384)
    b = embed_text("normalizePaymentAmount rounds the charge", 384)
    assert np.array_equal(a, b)


def test_normalized_nonempty():
    v = embed_text("a decision about the checkout transaction boundary", 384)
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5


def test_empty_is_zero_vector():
    v = embed_text("", 384)
    assert float(np.linalg.norm(v)) == 0.0


def test_index_vector_is_sparse_ternary():
    v = index_vector("payment", 384)
    nz = v[v != 0]
    assert len(nz) <= 8  # source: CBM_SEM_SPARSE_NNZE=8
    assert set(np.unique(nz)).issubset({-1.0, 1.0})


def test_semantic_ordering():
    q = embed_text("how to normalize a payment amount", 384)
    related = embed_text("payment normalization converts the amount to cents", 384)
    unrelated = embed_text("the weather in Paris was cold and rainy", 384)
    assert _cos(q, related) > _cos(q, unrelated)


def test_camelcase_bridges_to_words():
    q = embed_text("payment amount", 384)
    camel = embed_text("normalizePaymentAmount", 384)
    unrelated = embed_text("mountain hiking trip", 384)
    assert _cos(q, camel) > _cos(q, unrelated)
