"""Tests for mcp_server.shared.sparse — sparse vector operations."""

import pytest

from mcp_server.shared.sparse import (
    dense_to_sparse,
    sparse_add,
    sparse_cosine,
    sparse_dot,
    sparse_norm,
    sparse_scale,
    sparse_to_dense,
    sparse_top_k,
)


class TestSparseDot:
    def test_empty_dicts(self):
        assert sparse_dot({}, {}) == 0

    def test_disjoint_keys(self):
        assert sparse_dot({"x": 1}, {"y": 2}) == 0

    def test_overlapping_keys(self):
        a = {"x": 2, "y": 3}
        b = {"x": 4, "y": 5, "z": 6}
        assert sparse_dot(a, b) == 23  # 2*4 + 3*5

    def test_is_symmetric(self):
        a = {"a": 1, "b": 2}
        b = {"b": 3, "c": 4}
        assert sparse_dot(a, b) == sparse_dot(b, a)


class TestSparseNorm:
    def test_empty(self):
        assert sparse_norm({}) == 0

    def test_computes_l2(self):
        assert sparse_norm({"x": 3, "y": 4}) == 5


class TestSparseAdd:
    def test_adds_vectors(self):
        a = {"x": 1, "y": 2}
        b = {"y": 3, "z": 4}
        result = sparse_add(a, b)
        assert result["x"] == 1
        assert result["y"] == 5
        assert result["z"] == 4

    def test_removes_zero_sum(self):
        result = sparse_add({"x": 5}, {"x": -5})
        assert "x" not in result

    def test_empty_map(self):
        result = sparse_add({"x": 1}, {})
        assert result["x"] == 1


class TestSparseScale:
    def test_scales(self):
        result = sparse_scale({"x": 2, "y": 3}, 3)
        assert result["x"] == 6
        assert result["y"] == 9

    def test_scale_by_0(self):
        result = sparse_scale({"x": 1}, 0)
        assert len(result) == 0


class TestSparseTopK:
    def test_returns_top_k(self):
        v = {"a": 1, "b": -5, "c": 3, "d": -2}
        result = sparse_top_k(v, 2)
        assert len(result) == 2
        assert "b" in result
        assert "c" in result

    def test_returns_all_if_k_ge_size(self):
        result = sparse_top_k({"a": 1, "b": 2}, 5)
        assert len(result) == 2

    def test_empty(self):
        assert len(sparse_top_k({}, 3)) == 0


class TestSparseCosine:
    def test_empty(self):
        assert sparse_cosine({}, {}) == 0

    def test_identical(self):
        v = {"x": 1, "y": 2}
        assert sparse_cosine(v, v) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert sparse_cosine({"x": 1}, {"y": 1}) == 0

    def test_in_range(self):
        a = {"x": 1, "y": -3}
        b = {"x": -2, "y": 4}
        result = sparse_cosine(a, b)
        assert -1 <= result <= 1


class TestDenseToSparse:
    def test_converts(self):
        result = dense_to_sparse([1, 0, 3], ["a", "b", "c"])
        assert result["a"] == 1
        assert "b" not in result
        assert result["c"] == 3

    def test_respects_threshold(self):
        result = dense_to_sparse([0.001, 0.1], ["a", "b"], threshold=0.01)
        assert "a" not in result
        assert result["b"] == 0.1

    def test_empty(self):
        assert len(dense_to_sparse([], [])) == 0


class TestSparseToDense:
    def test_converts(self):
        result = sparse_to_dense({"b": 5, "c": 3}, ["a", "b", "c"])
        assert result == [0, 5, 3]

    def test_empty_sparse(self):
        assert sparse_to_dense({}, ["a", "b"]) == [0, 0]
