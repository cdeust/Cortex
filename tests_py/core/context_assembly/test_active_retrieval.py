"""Tests for mcp_server.core.context_assembly.active_retrieval (#196).

Imported by stage_assembler.py's optional query-reformulation step but
sat at 0% coverage.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.active_retrieval import (
    KeywordExtractor,
    LLMReformulator,
)


class TestKeywordExtractor:
    def test_empty_query_returns_unchanged(self):
        ex = KeywordExtractor()
        assert ex.reformulate("") == ""

    def test_whitespace_only_query_returns_unchanged(self):
        ex = KeywordExtractor()
        assert ex.reformulate("   ") == "   "

    def test_drops_question_words_and_filler(self):
        ex = KeywordExtractor()
        result = ex.reformulate("What is the deployment process for staging?")
        assert "what" not in result.lower()
        assert "deployment" in result

    def test_preserves_quoted_strings(self):
        ex = KeywordExtractor()
        result = ex.reformulate("What did I say about 'the migration plan'?")
        assert "the migration plan" in result

    def test_preserves_double_quoted_strings(self):
        ex = KeywordExtractor()
        result = ex.reformulate('When did I mention "database schema"?')
        assert "database schema" in result

    def test_preserves_iso_dates(self):
        ex = KeywordExtractor()
        result = ex.reformulate("What happened on 2024-03-15?")
        assert "2024-03-15" in result

    def test_preserves_slash_dates(self):
        ex = KeywordExtractor()
        result = ex.reformulate("What happened on 3/15/2024?")
        assert "3/15/2024" in result

    def test_preserves_month_name_dates(self):
        ex = KeywordExtractor()
        result = ex.reformulate("What happened on March 15, 2024?")
        assert "March 15, 2024" in result or "march 15, 2024" in result.lower()

    def test_keeps_capitalized_words_regardless_of_length(self):
        ex = KeywordExtractor()
        result = ex.reformulate("What did Bob say?")
        assert "Bob" in result

    def test_keeps_long_lowercase_words(self):
        ex = KeywordExtractor()
        result = ex.reformulate("the deployment configuration changed")
        assert "deployment" in result
        assert "configuration" in result

    def test_dedupes_case_insensitively_preserving_first_occurrence(self):
        ex = KeywordExtractor()
        result = ex.reformulate("Docker docker DOCKER container")
        assert result.lower().split().count("docker") == 1

    def test_no_keywords_extracted_returns_original_query(self):
        ex = KeywordExtractor()
        # All short/question/filler words, nothing >=4 chars or capitalized.
        result = ex.reformulate("is it a the")
        assert result == "is it a the"


class TestLLMReformulator:
    def test_no_llm_fn_returns_query_unchanged(self):
        reformer = LLMReformulator()
        assert reformer.reformulate("original query") == "original query"

    def test_calls_llm_fn_and_returns_stripped_result(self):
        reformer = LLMReformulator(llm_fn=lambda prompt: "  rewritten query  ")
        assert reformer.reformulate("original") == "rewritten query"

    def test_llm_fn_receives_formatted_prompt(self):
        captured = {}

        def fake_llm(prompt: str) -> str:
            captured["prompt"] = prompt
            return "result"

        reformer = LLMReformulator(llm_fn=fake_llm)
        reformer.reformulate("my question")
        assert "my question" in captured["prompt"]

    def test_llm_fn_returning_empty_string_falls_back_to_original(self):
        reformer = LLMReformulator(llm_fn=lambda prompt: "   ")
        assert reformer.reformulate("original") == "original"

    def test_llm_fn_returning_non_string_falls_back_to_original(self):
        reformer = LLMReformulator(llm_fn=lambda prompt: None)
        assert reformer.reformulate("original") == "original"

    def test_llm_fn_raising_exception_falls_back_to_original(self):
        def broken_llm(prompt: str) -> str:
            raise RuntimeError("model unavailable")

        reformer = LLMReformulator(llm_fn=broken_llm)
        assert reformer.reformulate("original") == "original"
