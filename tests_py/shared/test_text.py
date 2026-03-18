"""Tests for mcp_server.shared.text — keyword extraction."""

from mcp_server.shared.text import (
    STOPWORDS,
    TECHNICAL_SHORT_TERMS,
    extract_keywords,
    extract_keywords_array,
)


class TestExtractKeywords:
    def test_returns_empty_set_for_empty_string(self):
        result = extract_keywords("")
        assert isinstance(result, set)
        assert len(result) == 0

    def test_returns_empty_set_for_none(self):
        assert len(extract_keywords(None)) == 0

    def test_handles_unicode_text_without_crashing(self):
        result = extract_keywords("configuración del servidor autenticación")
        assert isinstance(result, set)

    def test_extracts_technical_abbreviations(self):
        result = extract_keywords("use the api to run sql queries")
        assert "api" in result
        assert "sql" in result

    def test_handles_mixed_case_by_lowercasing(self):
        result = extract_keywords("API SQL Authentication")
        assert "api" in result
        assert "sql" in result
        assert "authentication" in result

    def test_passes_words_longer_than_6_characters(self):
        result = extract_keywords("refactoring authentication middleware")
        assert "refactoring" in result
        assert "authentication" in result
        assert "middleware" in result

    def test_filters_out_short_non_technical_words(self):
        result = extract_keywords("the cat sat on a mat")
        assert len(result) == 0

    def test_handles_long_text(self):
        long_text = "authentication " * 1000 + "api sql debugging"
        result = extract_keywords(long_text)
        assert "authentication" in result
        assert "api" in result
        assert "sql" in result
        assert "debugging" in result

    def test_deduplicates_keywords(self):
        result = extract_keywords("api api api authentication authentication")
        assert len(result) == 2
        assert "api" in result
        assert "authentication" in result


class TestExtractKeywordsArray:
    def test_returns_a_list(self):
        result = extract_keywords_array("api authentication")
        assert isinstance(result, list)

    def test_returns_empty_list_for_empty_string(self):
        result = extract_keywords_array("")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_contains_same_elements_as_extract_keywords(self):
        text = "api authentication middleware"
        kw_set = extract_keywords(text)
        kw_arr = extract_keywords_array(text)
        assert len(kw_arr) == len(kw_set)
        for kw in kw_arr:
            assert kw in kw_set


class TestStopwordsFiltering:
    def test_excludes_common_stopwords_from_results(self):
        samples = ["the", "and", "for", "with", "from", "this", "that"]
        for sw in samples:
            result = extract_keywords(sw)
            assert sw not in result, f'stopword "{sw}" should not appear in results'

    def test_stopwords_set_contains_common_english_words(self):
        assert "the" in STOPWORDS
        assert "and" in STOPWORDS
        assert "for" in STOPWORDS
        assert "with" in STOPWORDS
        assert "about" in STOPWORDS


class TestTechnicalShortTerms:
    def test_includes_known_short_technical_terms(self):
        for term in ("api", "sql", "jwt", "cli", "mcp", "git"):
            assert term in TECHNICAL_SHORT_TERMS

    def test_extract_keywords_picks_up_technical_short_terms(self):
        terms = ["api", "sql", "jwt", "cli", "mcp", "git", "auth", "ssh", "npm"]
        for term in terms:
            result = extract_keywords(f"use {term} here")
            assert term in result, f'technical term "{term}" should be extracted'

    def test_technical_short_terms_is_frozenset(self):
        assert isinstance(TECHNICAL_SHORT_TERMS, frozenset)
        assert len(TECHNICAL_SHORT_TERMS) > 0
