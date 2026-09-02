"""Tests for code-aware sub-token splitting (issue #169).

Contract assertions (each must fail on regression):
  - split_identifier decomposes camelCase, snake_case, acronyms, digit runs
  - split_identifier is idempotent and lowercases
  - augment_content appends sub-tokens only for splittable identifiers
  - expand_fts_query is FTS5-safe (quoted) and preserves AND-across-words
"""

from __future__ import annotations

import sqlite3

import pytest

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
    # two required groups, joined with an explicit AND (FTS5 grammar rejects
    # implicit-AND when either side is a parenthesized group — see regression
    # test below).
    assert q == '"payment" AND "amount"'


def test_expand_query_fts5_keyword_is_literal():
    # bare 'OR' would be an operator; quoting makes it a literal term
    assert expand_fts_query("OR") == '"or"'


def test_expand_query_empty():
    assert expand_fts_query("!!!") == ""


# --- Regression: FTS5 grammar acceptance (get_causal_chain crash) -----------
# The bug: expand_fts_query joined its groups with whitespace, so a query
# mixing a multi-token word (→ "(a OR b)" group) with a single-token word
# (→ bare "c" phrase) produced "(a OR b) \"c\"", which FTS5 rejects with
# 'fts5: syntax error near ...'. An entity named cortex_viz/__main__.py hit
# exactly this on the SQLite backend and crashed get_causal_chain.


def _fts5_available() -> bool:
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.close()
        return True
    except sqlite3.OperationalError:
        return False


@pytest.mark.skipif(not _fts5_available(), reason="sqlite3 built without FTS5")
@pytest.mark.parametrize(
    "query",
    [
        "cortex_viz/__main__.py",  # group then bare phrase — the original crash
        "__main__ cortex_viz",  # bare phrase then group — the mirror case
        "normalizePaymentAmount rounds the total",  # group amid plain words
        "utf8 payment snake_case_id",  # multiple groups and phrases interleaved
    ],
)
def test_expanded_query_is_accepted_by_real_fts5(query: str) -> None:
    match = expand_fts_query(query)
    assert match  # each query has at least one indexable word
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.execute("INSERT INTO t(x) VALUES (?)", ("cortex viz main payment",))
        # The assertion is that MATCH parses at all — no OperationalError.
        con.execute("SELECT rowid FROM t WHERE t MATCH ?", (match,)).fetchall()
    finally:
        con.close()


@pytest.mark.skipif(not _fts5_available(), reason="sqlite3 built without FTS5")
def test_group_and_phrase_are_and_joined() -> None:
    # A group followed by a bare phrase must be joined so both are REQUIRED:
    # the row matches only when it contains a sub-token of the group AND the
    # phrase — proving the join is a conjunction, not a dropped/broken clause.
    match = expand_fts_query("cortex_viz rounds")
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.execute("INSERT INTO t(x) VALUES (?)", ("cortex rounds the total",))
        con.execute("INSERT INTO t(x) VALUES (?)", ("cortex only",))  # no 'rounds'
        rows = con.execute(
            "SELECT x FROM t WHERE t MATCH ? ORDER BY rowid", (match,)
        ).fetchall()
        assert rows == [("cortex rounds the total",)]
    finally:
        con.close()
