"""Mutation-hardening contract tests for condense_text.py (issue #228).

A scoped mutmut run over the pre-split condensers.py left survivors in
condense_user_message (12) and condense_timeline_event (15) that no test in
test_condensers.py could distinguish — behaviours a substring/`in`
assertion cannot see. Each test below pins one such observable contract: a
budget boundary, an accounting step, or a slice length, via exact-equality
assertions.

Budgets are chosen so the arithmetic is exact: ``estimate_tokens`` is
``len(text) // 3``, so a text of ``3 * N`` characters is worth exactly
``N`` tokens and a boundary can be hit on the nose.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.condense_text import (
    _first_sentence,
    _split_sentences,
    condense_timeline_event,
    condense_user_message,
)

# Three sentences, one of them pure filler: condensing drops the middle,
# so "returned verbatim" and "condensed" are trivially distinguishable.
THREE_SENTENCES = "One. Two. Three."
THREE_SENTENCES_TOKENS = 5  # len == 16, 16 // 3 == 5

# First + both questions + last, joined by a single space (38 chars).
QUESTION_TEXT = "Intro line. Q one? Filler mid. Q two? Ending line."
QUESTION_KEPT = "Intro line. Q one? Q two? Ending line."


# ── condense_user_message ─────────────────────────────────────────────


def test_user_message_at_exact_budget_is_returned_verbatim() -> None:
    """``estimate_tokens(text) == token_budget`` takes the no-op path."""
    assert estimate_tokens(THREE_SENTENCES) == THREE_SENTENCES_TOKENS

    assert condense_user_message(THREE_SENTENCES, THREE_SENTENCES_TOKENS) == (
        THREE_SENTENCES
    )
    # One token tighter and the middle sentence is dropped — proof the
    # verbatim result above is the boundary, not a coincidence.
    assert condense_user_message(THREE_SENTENCES, 4) == "One. Three."


def test_two_sentence_message_truncates_the_original_not_the_rejoin() -> None:
    """A 2-sentence text truncates ``text``, keeping its line structure.

    The first+last rebuild would re-join the two sentences with a single
    space, destroying the newline ``truncate_to_budget`` cuts on.
    """
    text = "First sentence here.\n" + "Second sentence " * 50

    assert condense_user_message(text, 10) == "First sentence here.\n"


def test_user_message_keeps_every_middle_question_in_order() -> None:
    """All interrogative middles survive; non-question middles do not."""
    out = condense_user_message(QUESTION_TEXT, 13)

    assert out == QUESTION_KEPT
    assert "Filler mid." not in out


def test_user_message_result_at_exact_budget_is_not_truncated() -> None:
    """The rebuilt result is returned whole when it lands exactly on budget."""
    assert estimate_tokens(QUESTION_KEPT) == 12

    assert condense_user_message(QUESTION_TEXT, 12) == QUESTION_KEPT
    # One token tighter and the same rebuild is cut to 12 * 3 chars.
    assert condense_user_message(QUESTION_TEXT, 11) == QUESTION_KEPT[:33]


def test_user_message_truncates_the_rejoined_result_when_over_budget() -> None:
    """Question-dense text keeps the rebuild over budget, so it is cut."""
    text = "Intro. " + "Why? " * 40 + "Ending."

    out = condense_user_message(text, 10)

    assert out == "Intro. Why? Why? Why? Why? Why"
    assert estimate_tokens(out) <= 10


# ── condense_timeline_event ───────────────────────────────────────────

_TIMELINE_FILLER = "Then filler. " * 60
ISO_EVENT = "On 2026-07-14 the reranker was disabled. " + _TIMELINE_FILLER
ISO_COMPRESSED = "[2026-07-14] On 2026-07-14 the reranker was disabled."


def test_timeline_event_at_exact_budget_is_returned_verbatim() -> None:
    text = "Short. Text."  # 12 chars -> 4 tokens
    assert estimate_tokens(text) == 4

    assert condense_timeline_event(text, 4) == text
    assert condense_timeline_event(text, 3) == "Short."


def test_timeline_event_reads_the_bracketed_date_marker() -> None:
    """The ``[Date: ...]`` slot is matched case-sensitively, group 1 first."""
    text = (
        "[Date: yesterday afternoon] The store was migrated. "
        + "Filler words here. " * 60
    )

    assert condense_timeline_event(text, 40) == (
        "[yesterday afternoon] [Date: yesterday afternoon] The store was migrated."
    )


def test_timeline_event_reads_an_iso_date() -> None:
    """A bare ``YYYY-MM-DD`` is the second alternative, read from group 2."""
    assert condense_timeline_event(ISO_EVENT, 40) == ISO_COMPRESSED


def test_timeline_event_reads_a_month_day_year_date() -> None:
    """``Month D, YYYY`` is the third alternative, read from group 3.

    Groups 1 and 2 are both None here, so this is the only shape that
    forces the third ``or`` arm to be evaluated at all.
    """
    text = "Shipped March 4, 2026 to production. " + _TIMELINE_FILLER

    assert condense_timeline_event(text, 40) == (
        "[March 4, 2026] Shipped March 4, 2026 to production."
    )


def test_timeline_event_compressed_at_exact_budget_is_not_truncated() -> None:
    assert estimate_tokens(ISO_COMPRESSED) == 17

    assert condense_timeline_event(ISO_EVENT, 17) == ISO_COMPRESSED


def test_timeline_event_truncates_the_compressed_form_not_the_raw_text() -> None:
    """Over budget, the slot-filled string is what gets cut — not ``text``."""
    out = condense_timeline_event(ISO_EVENT, 16)

    assert out == ISO_COMPRESSED[:48]


# ── helpers ───────────────────────────────────────────────────────────


def test_first_sentence_returns_the_first_sentence_not_the_whole_text() -> None:
    assert _first_sentence("First. Second. Third.") == "First."
    # No terminator anywhere: the whole text IS the first sentence.
    assert _first_sentence("no terminator here") == "no terminator here"
    assert _first_sentence("") == ""


def test_split_sentences_strips_and_drops_empty_parts() -> None:
    """Leading/trailing whitespace is stripped before splitting."""
    assert _split_sentences("  One. Two.  ") == ["One.", "Two."]
    assert _split_sentences("") == []
