"""Tests for code-aware sub-token splitting (issue #169).

Contract assertions (each must fail on regression):
  - split_identifier decomposes camelCase, snake_case, acronyms, digit runs
  - split_identifier is idempotent and lowercases
  - augment_content appends sub-tokens only for splittable identifiers
  - expand_fts_query is FTS5-safe (quoted) and preserves AND-across-words
"""

from __future__ import annotations

from mcp_server.shared.code_tokenize import (
    augment_content,
    expand_fts_query,
    split_identifier,
)


def test_split_camel_case():
    assert split_identifier("normalizePaymentAmount") == [
        "normalize",
        "payment",
        "amount",
    ]


def test_split_snake_and_kebab():
    assert split_identifier("snake_case_id") == ["snake", "case", "id"]
    assert split_identifier("kebab-case-thing") == ["kebab", "case", "thing"]


def test_split_acronym_boundary():
    assert split_identifier("HTTPRequest") == ["http", "request"]


def test_split_digit_boundary():
    assert split_identifier("utf8") == ["utf", "8"]


def test_split_plain_word_is_single_lowercased():
    assert split_identifier("payment") == ["payment"]
    assert split_identifier("Payment") == ["payment"]


def test_split_is_idempotent_on_subtokens():
    for sub in split_identifier("normalizePaymentAmount"):
        assert split_identifier(sub) == [sub]


def test_split_empty():
    assert split_identifier("") == []


def test_augment_appends_subtokens():
    out = augment_content("normalizePaymentAmount rounds")
    assert out.startswith("normalizePaymentAmount rounds")
    assert "payment" in out.split()
    assert "amount" in out.split()


def test_augment_noop_without_identifiers():
    text = "the quick brown fox"
    assert augment_content(text) == text


def test_augment_does_not_duplicate_present_words():
    # 'payment' already a standalone word → not re-appended
    out = augment_content("payment normalizePaymentAmount")
    assert out.split().count("payment") == 1


def test_expand_query_quotes_and_expands():
    q = expand_fts_query("normalizePaymentAmount")
    assert q.startswith("(")
    assert '"payment"' in q
    assert "OR" in q


def test_expand_query_preserves_and_across_words():
    q = expand_fts_query("payment amount")
    # two required groups, whitespace-joined (FTS5 implicit AND)
    assert q == '"payment" "amount"'


def test_expand_query_fts5_keyword_is_literal():
    # bare 'OR' would be an operator; quoting makes it a literal term
    assert expand_fts_query("OR") == '"or"'


def test_expand_query_empty():
    assert expand_fts_query("!!!") == ""
