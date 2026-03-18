"""Tests for mcp_server.shared.similarity — Jaccard similarity."""

from mcp_server.shared.similarity import jaccard_similarity


class TestJaccardSimilarity:
    def test_returns_0_for_two_empty_sets(self):
        assert jaccard_similarity(set(), set()) == 0

    def test_returns_1_for_identical_sets(self):
        s = {"a", "b", "c"}
        assert jaccard_similarity(s, s) == 1

    def test_returns_1_for_equal_but_different_instances(self):
        a = {"x", "y", "z"}
        b = {"x", "y", "z"}
        assert jaccard_similarity(a, b) == 1

    def test_returns_0_for_disjoint_sets(self):
        assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0

    def test_correct_value_for_partial_overlap(self):
        a = {"a", "b", "c"}
        b = {"b", "c", "d"}
        assert jaccard_similarity(a, b) == 0.5

    def test_single_element_identical(self):
        assert jaccard_similarity({"x"}, {"x"}) == 1

    def test_single_element_disjoint(self):
        assert jaccard_similarity({"x"}, {"y"}) == 0

    def test_returns_0_when_one_set_empty(self):
        assert jaccard_similarity(set(), {"a"}) == 0
        assert jaccard_similarity({"a"}, set()) == 0

    def test_is_symmetric(self):
        a = {"a", "b", "c"}
        b = {"c", "d", "e"}
        assert jaccard_similarity(a, b) == jaccard_similarity(b, a)

    def test_result_between_0_and_1(self):
        a = {"a", "b", "c", "d"}
        b = {"c", "d", "e"}
        result = jaccard_similarity(a, b)
        assert 0 <= result <= 1
