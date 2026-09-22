"""The pointer predicate and its truncation helper (issue #622).

``is_pointer_source`` is the single authority on whether a memory is a
wiki-page pointer. Two enforcement points consult it — ``wiki_sync`` in
Python and ``wiki_extract`` over rows a SQL pre-filter narrowed — so its
edges matter more than a private helper's normally would: an input the
predicate and the pre-filter disagree about is an input that can reopen
the loop.
"""

from __future__ import annotations

import pytest

from mcp_server.shared.wiki_pointer import (
    POINTER_CONTENT_MAX_CHARS,
    WIKI_POINTER_SOURCE_LIKE,
    is_pointer_source,
    not_a_pointer_sql,
    pointer_source,
    truncate_on_word_boundary,
)


# ── The predicate ────────────────────────────────────────────────────────


def test_a_pointer_origin_is_recognised():
    assert is_pointer_source(pointer_source("explanation/x/page.md"))


@pytest.mark.parametrize(
    "padded",
    [
        " wiki://explanation/x/page.md",
        "wiki://explanation/x/page.md ",
        "\twiki://explanation/x/page.md\n",
    ],
)
def test_padding_does_not_hide_a_pointer(padded):
    """The SQL pre-filter's LIKE cannot see through padding; this can.

    That asymmetry is deliberate and one-directional: the predicate is
    the stricter of the two and runs last, so a value LIKE waved through
    is still turned away. A predicate that did not strip would let a
    padded row into the drafting chain.
    """
    assert is_pointer_source(padded)


@pytest.mark.parametrize(
    "not_a_pointer",
    [None, "", "   ", "user", "session", "consolidation", "backfill:notes"],
)
def test_ordinary_origins_are_not_pointers(not_a_pointer):
    assert not is_pointer_source(not_a_pointer)


def test_the_bare_scheme_names_no_page_and_is_not_a_pointer():
    """``wiki://`` with no path points at nothing.

    Narrows the collision surface for a caller that ignores
    ``remember``'s source enum: only the full shape ``pointer_source``
    produces excludes a memory from materialisation.
    """
    assert not is_pointer_source("wiki://")
    assert is_pointer_source("wiki://a")


# ── The SQL fragment builder ─────────────────────────────────────────────


def test_the_sql_fragment_carries_its_own_bind_param():
    clause, params = not_a_pointer_sql("m.source")

    assert clause == "(m.source IS NULL OR m.source NOT LIKE %s)"
    assert params == (WIKI_POINTER_SOURCE_LIKE,)


def test_the_sql_fragment_follows_the_column_it_is_given():
    clause, _ = not_a_pointer_sql("memories.source")

    assert clause.count("memories.source") == 2


# ── The truncation ───────────────────────────────────────────────────────


def test_truncate_keeps_whole_words():
    text = "la règle qui garde les couches séparées " * 40
    cut = truncate_on_word_boundary(text, 100)

    assert len(cut) <= 100
    assert cut.endswith("…")
    assert not cut[:-1].endswith(" ")
    assert f"{cut[:-1].rsplit(' ', 1)[-1]} " in text


def test_truncate_leaves_short_text_untouched():
    assert truncate_on_word_boundary("short", 100) == "short"


def test_truncate_still_bounds_a_single_long_token():
    cut = truncate_on_word_boundary("x" * 300, 50)

    assert len(cut) <= 50
    assert cut.endswith("…")


@pytest.mark.parametrize("limit", [0, 1, -10])
def test_a_limit_too_small_to_mark_the_cut_is_refused(limit):
    """Exported as a general helper, so the precondition is enforced.

    Silently returning a string that overruns the budget, or one with no
    ellipsis, would push the defect onto the caller.
    """
    with pytest.raises(ValueError, match="ellipsis width"):
        truncate_on_word_boundary("some text that needs cutting", limit)


def test_the_default_limit_is_the_pointer_budget():
    assert len(truncate_on_word_boundary("word " * 400)) <= POINTER_CONTENT_MAX_CHARS
