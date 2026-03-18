"""Tests for mcp_server.core.hopfield — Modern Hopfield Networks."""

import numpy as np

from mcp_server.core.hopfield import (
    build_pattern_matrix,
    retrieve,
    retrieve_sparse,
    pattern_completion,
    compute_energy,
    cosine_similarity,
)


def _make_embedding(vec: list[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


DIM = 4


class TestBuildPatternMatrix:
    def test_basic_construction(self):
        embs = [
            (1, _make_embedding([1.0, 0.0, 0.0, 0.0])),
            (2, _make_embedding([0.0, 1.0, 0.0, 0.0])),
        ]
        matrix, ids = build_pattern_matrix(embs, DIM)
        assert matrix.shape == (2, DIM)
        assert ids == [1, 2]

    def test_empty_patterns(self):
        matrix, ids = build_pattern_matrix([], DIM)
        assert matrix.shape[0] == 0
        assert ids == []

    def test_wrong_dim_skipped(self):
        embs = [
            (1, _make_embedding([1.0, 0.0])),  # wrong dim
            (2, _make_embedding([0.0, 1.0, 0.0, 0.0])),  # correct
        ]
        matrix, ids = build_pattern_matrix(embs, DIM)
        assert matrix.shape[0] == 1
        assert ids == [2]

    def test_rows_are_normalized(self):
        embs = [(1, _make_embedding([3.0, 4.0, 0.0, 0.0]))]
        matrix, _ = build_pattern_matrix(embs, DIM)
        norm = float(np.linalg.norm(matrix[0]))
        assert abs(norm - 1.0) < 1e-5


class TestRetrieve:
    def test_retrieves_nearest_pattern(self):
        embs = [
            (1, _make_embedding([1.0, 0.0, 0.0, 0.0])),
            (2, _make_embedding([0.0, 1.0, 0.0, 0.0])),
            (3, _make_embedding([0.0, 0.0, 1.0, 0.0])),
        ]
        matrix, ids = build_pattern_matrix(embs, DIM)
        query = _make_embedding([0.9, 0.1, 0.0, 0.0])
        results = retrieve(query, matrix, ids, beta=8.0)
        # First pattern should have highest attention
        assert results[0][0] == 1

    def test_empty_matrix(self):
        matrix, ids = build_pattern_matrix([], DIM)
        query = _make_embedding([1.0, 0.0, 0.0, 0.0])
        assert retrieve(query, matrix, ids) == []

    def test_top_k_limits(self):
        embs = [
            (i, _make_embedding([float(i == j) for j in range(DIM)]))
            for i in range(DIM)
        ]
        matrix, ids = build_pattern_matrix(embs, DIM)
        query = _make_embedding([1.0, 0.0, 0.0, 0.0])
        results = retrieve(query, matrix, ids, top_k=2)
        assert len(results) <= 2


class TestRetrieveSparse:
    def test_sparse_concentrates_weight(self):
        embs = [
            (1, _make_embedding([1.0, 0.0, 0.0, 0.0])),
            (2, _make_embedding([0.0, 1.0, 0.0, 0.0])),
        ]
        matrix, ids = build_pattern_matrix(embs, DIM)
        query = _make_embedding([1.0, 0.0, 0.0, 0.0])
        results = retrieve_sparse(query, matrix, ids, beta=8.0)
        # Should strongly favor pattern 1
        assert len(results) >= 1
        assert results[0][0] == 1

    def test_empty_matrix(self):
        matrix, ids = build_pattern_matrix([], DIM)
        query = _make_embedding([1.0, 0.0, 0.0, 0.0])
        assert retrieve_sparse(query, matrix, ids) == []


class TestPatternCompletion:
    def test_completes_to_nearest_pattern(self):
        embs = [
            (1, _make_embedding([1.0, 0.0, 0.0, 0.0])),
            (2, _make_embedding([0.0, 1.0, 0.0, 0.0])),
        ]
        matrix, _ = build_pattern_matrix(embs, DIM)
        partial = _make_embedding([0.8, 0.1, 0.0, 0.0])
        completed = pattern_completion(partial, matrix, beta=8.0)
        assert isinstance(completed, bytes)
        # Should be closer to first pattern
        sim1 = cosine_similarity(completed, _make_embedding([1.0, 0.0, 0.0, 0.0]))
        sim2 = cosine_similarity(completed, _make_embedding([0.0, 1.0, 0.0, 0.0]))
        assert sim1 > sim2

    def test_empty_matrix_returns_input(self):
        matrix, _ = build_pattern_matrix([], DIM)
        query = _make_embedding([1.0, 0.0, 0.0, 0.0])
        result = pattern_completion(query, matrix)
        assert isinstance(result, bytes)


class TestComputeEnergy:
    def test_stored_pattern_low_energy(self):
        embs = [(1, _make_embedding([1.0, 0.0, 0.0, 0.0]))]
        matrix, _ = build_pattern_matrix(embs, DIM)
        energy_stored = compute_energy(
            _make_embedding([1.0, 0.0, 0.0, 0.0]), matrix, beta=4.0
        )
        energy_novel = compute_energy(
            _make_embedding([0.0, 0.0, 0.0, 1.0]), matrix, beta=4.0
        )
        assert energy_stored < energy_novel

    def test_energy_is_finite(self):
        embs = [(i, _make_embedding(np.random.randn(DIM).tolist())) for i in range(3)]
        matrix, _ = build_pattern_matrix(embs, DIM)
        energy = compute_energy(
            _make_embedding(np.random.randn(DIM).tolist()), matrix, beta=8.0
        )
        assert np.isfinite(energy)

    def test_empty_matrix(self):
        matrix, _ = build_pattern_matrix([], DIM)
        energy = compute_energy(_make_embedding([1.0, 0.0, 0.0, 0.0]), matrix)
        assert np.isfinite(energy)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = _make_embedding([1.0, 2.0, 3.0, 0.0])
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-5

    def test_orthogonal_vectors(self):
        a = _make_embedding([1.0, 0.0, 0.0, 0.0])
        b = _make_embedding([0.0, 1.0, 0.0, 0.0])
        assert abs(cosine_similarity(a, b)) < 1e-5

    def test_opposite_vectors(self):
        a = _make_embedding([1.0, 0.0, 0.0, 0.0])
        b = _make_embedding([-1.0, 0.0, 0.0, 0.0])
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-5

    def test_zero_vector(self):
        a = _make_embedding([0.0, 0.0, 0.0, 0.0])
        b = _make_embedding([1.0, 2.0, 3.0, 0.0])
        assert cosine_similarity(a, b) == 0.0
