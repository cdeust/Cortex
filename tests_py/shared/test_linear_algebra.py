"""Tests for mcp_server.shared.linear_algebra — dense vector math."""

import pytest

from mcp_server.shared.linear_algebra import (
    add,
    clamp,
    cosine_similarity,
    dot,
    norm,
    normalize,
    project,
    scale,
    subtract,
    zeros,
)


class TestDot:
    def test_returns_0_for_empty_vectors(self):
        assert dot([], []) == 0

    def test_computes_dot_product(self):
        assert dot([1, 2, 3], [4, 5, 6]) == 32

    def test_handles_unequal_lengths(self):
        assert dot([1, 2], [3, 4, 5]) == 11

    def test_returns_0_for_orthogonal(self):
        assert dot([1, 0], [0, 1]) == 0


class TestNorm:
    def test_returns_0_for_empty(self):
        assert norm([]) == 0

    def test_returns_0_for_zero_vector(self):
        assert norm([0, 0, 0]) == 0

    def test_computes_l2_norm(self):
        assert norm([3, 4]) == 5

    def test_single_element(self):
        assert norm([7]) == 7


class TestNormalize:
    def test_zero_vector(self):
        assert normalize([0, 0]) == [0, 0]

    def test_unit_vector(self):
        result = normalize([3, 4])
        assert result[0] == pytest.approx(0.6)
        assert result[1] == pytest.approx(0.8)

    def test_normalized_has_norm_1(self):
        result = normalize([1, 2, 3, 4])
        assert norm(result) == pytest.approx(1.0)


class TestCosineSimilarity:
    def test_returns_0_for_zero_vector(self):
        assert cosine_similarity([0, 0], [1, 2]) == 0
        assert cosine_similarity([1, 2], [0, 0]) == 0

    def test_returns_1_for_same_direction(self):
        assert cosine_similarity([1, 2], [2, 4]) == pytest.approx(1.0)

    def test_returns_neg1_for_opposite(self):
        assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_returns_0_for_orthogonal(self):
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0, abs=1e-10)

    def test_is_symmetric(self):
        a, b = [1, 2, 3], [4, 5, 6]
        assert cosine_similarity(a, b) == pytest.approx(cosine_similarity(b, a))

    def test_result_in_range(self):
        result = cosine_similarity([1, -3, 2], [-4, 5, 1])
        assert -1 <= result <= 1


class TestAdd:
    def test_equal_length(self):
        assert add([1, 2], [3, 4]) == [4, 6]

    def test_unequal_lengths(self):
        assert add([1], [2, 3]) == [3, 3]

    def test_empty(self):
        assert add([], []) == []


class TestSubtract:
    def test_equal_length(self):
        assert subtract([5, 3], [1, 2]) == [4, 1]

    def test_unequal_lengths(self):
        assert subtract([1], [2, 3]) == [-1, -3]


class TestScale:
    def test_multiplies(self):
        assert scale([1, 2, 3], 2) == [2, 4, 6]

    def test_scale_by_0(self):
        assert scale([1, 2], 0) == [0, 0]

    def test_empty(self):
        assert scale([], 5) == []


class TestProject:
    def test_axis_aligned(self):
        result = project([3, 4], [1, 0])
        assert result[0] == pytest.approx(3)
        assert result[1] == pytest.approx(0)

    def test_onto_zero(self):
        assert project([1, 2], [0, 0]) == [0, 0]

    def test_onto_itself(self):
        result = project([3, 4], [3, 4])
        assert result[0] == pytest.approx(3)
        assert result[1] == pytest.approx(4)


class TestClamp:
    def test_clamps_values(self):
        assert clamp([-2, 0.5, 3], -1, 1) == [-1, 0.5, 1]

    def test_already_in_range(self):
        assert clamp([0, 0.5, 1], 0, 1) == [0, 0.5, 1]


class TestZeros:
    def test_creates_zero_vector(self):
        assert zeros(3) == [0, 0, 0]

    def test_dim_0(self):
        assert zeros(0) == []
