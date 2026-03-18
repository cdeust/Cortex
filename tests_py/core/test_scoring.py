"""Tests for mcp_server.core.scoring — BM25, n-gram, keyword overlap."""

from mcp_server.core.scoring import (
    compute_bm25_scores,
    compute_keyword_overlap,
    compute_ngram_score,
    tokenize,
    tokenize_raw,
)


class TestTokenize:
    def test_basic(self):
        tokens = tokenize_raw("Hello world test")
        assert tokens == ["hello", "world", "test"]

    def test_stopword_filtering(self):
        tokens = tokenize("the cat is on the mat")
        assert "the" not in tokens
        assert "cat" in tokens
        assert "mat" in tokens

    def test_empty(self):
        assert tokenize("") == []
        assert tokenize_raw("") == []


class TestBM25:
    def test_basic_scoring(self):
        docs = ["I love pizza", "The weather is nice", "My favorite food is sushi"]
        scores = compute_bm25_scores("favorite food", docs)
        assert len(scores) == 3
        assert scores[2] > scores[0]  # "favorite food" matches doc 3
        assert scores[2] > scores[1]

    def test_empty_query(self):
        assert compute_bm25_scores("", ["doc1", "doc2"]) == [0.0, 0.0]

    def test_empty_docs(self):
        assert compute_bm25_scores("query", []) == []

    def test_normalized(self):
        scores = compute_bm25_scores("test", ["test doc", "no match", "test test test"])
        assert max(scores) == 1.0
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_no_match(self):
        scores = compute_bm25_scores("xyz", ["abc def", "ghi jkl"])
        assert all(s == 0.0 for s in scores)


class TestNgramScore:
    def test_exact_phrase_match(self):
        score = compute_ngram_score("favorite food", "My favorite food is sushi")
        assert score > 0.0

    def test_no_match(self):
        score = compute_ngram_score("quantum physics", "I like pizza")
        assert score == 0.0

    def test_empty(self):
        assert compute_ngram_score("", "doc") == 0.0
        assert compute_ngram_score("query", "") == 0.0

    def test_partial_match(self):
        full = compute_ngram_score(
            "favorite food recipe", "My favorite food recipe is great"
        )
        partial = compute_ngram_score(
            "favorite food recipe", "My favorite food is great"
        )
        assert full >= partial


class TestKeywordOverlap:
    def test_full_overlap(self):
        score = compute_keyword_overlap("hello world", "hello world test")
        assert score == 1.0

    def test_partial_overlap(self):
        score = compute_keyword_overlap("hello world foo", "hello bar baz")
        assert 0.0 < score < 1.0

    def test_no_overlap(self):
        score = compute_keyword_overlap("abc", "xyz")
        assert score == 0.0

    def test_empty_query(self):
        assert compute_keyword_overlap("", "doc") == 0.0
