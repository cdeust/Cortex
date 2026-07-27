"""Tests for core/context_assembly/condensers — domain-aware reduction.

Each condenser claims to keep a specific kind of high-signal content
that generic truncation would lose. These tests assert that claim: the
signal survives, the filler does not, and the result respects the
budget. The reduction is exercised through the shape of the output, not
by mirroring the implementation.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.condensers import (
    condense_assistant_message,
    condense_code_block,
    condense_entity_triples,
    condense_memory_content,
    condense_timeline_event,
    condense_user_message,
)

# Every condenser returns input unchanged when it already fits; each test
# below that exercises reduction passes a budget well under the input.
FITS = 10_000


# ── condense_user_message ─────────────────────────────────────────────


def test_user_message_under_budget_is_untouched() -> None:
    text = "Just a short question?"

    assert condense_user_message(text, FITS) == text


def test_user_message_keeps_first_last_and_questions() -> None:
    text = (
        "I am refactoring the store. "
        + ("Some filler about unrelated context. " * 60)
        + "Should the cache stay warm? "
        + ("More filler prose here. " * 60)
        + "That is the whole problem."
    )

    out = condense_user_message(text, 60)

    assert out.startswith("I am refactoring the store.")
    assert "Should the cache stay warm?" in out
    assert out.endswith("That is the whole problem.")
    assert len(out) < len(text)


def test_two_sentence_message_falls_back_to_truncation() -> None:
    text = "First part here. " + "x" * 4000

    out = condense_user_message(text, 30)

    assert out.startswith("First part here.")
    assert estimate_tokens(out) <= 30


# ── condense_assistant_message ────────────────────────────────────────


def test_assistant_message_keeps_code_blocks_verbatim() -> None:
    text = (
        ("Long explanation sentence. " * 200)
        + "\n```python\ndef pay(amount):\n    return amount * 2\n```\n"
        + ("trailing prose. " * 200)
    )

    out = condense_assistant_message(text, 200)

    assert "def pay(amount):" in out
    assert "return amount * 2" in out
    assert len(out) < len(text)


def test_assistant_message_drops_code_blocks_past_the_budget() -> None:
    blocks = "".join(f"```\nblock_{i}()\n```\n" for i in range(40))

    out = condense_assistant_message(blocks, 20)

    assert "block_0()" in out
    assert "block_39()" not in out


def test_assistant_message_never_annihilates_an_oversized_code_block() -> None:
    # One block larger than the entire budget: keeping "first N blocks"
    # keeps none, and returning "" would delete the memory outright.
    text = "```\n" + "step()\n" * 400 + "```"

    out = condense_assistant_message(text, 20)

    assert out.strip(), "a non-empty memory must never condense to nothing"
    assert estimate_tokens(out) <= 20


# ── condense_entity_triples ───────────────────────────────────────────


def test_entity_triples_keeps_triple_lines_and_drops_prose() -> None:
    text = (
        "Here is some narrative preamble that carries no triple.\n"
        "recall → uses → pgvector\n"
        "store -> writes -> memories\n"
        + "More narrative filler that should not survive.\n" * 60
    )

    out = condense_entity_triples(text, 40)

    assert "recall → uses → pgvector" in out
    assert "narrative filler" not in out


def test_entity_triples_without_any_triple_falls_back_to_truncation() -> None:
    text = "no triples at all here. " * 300

    out = condense_entity_triples(text, 25)

    assert out
    assert estimate_tokens(out) <= 25


# ── condense_timeline_event ───────────────────────────────────────────


def test_timeline_event_pins_the_date_and_first_sentence() -> None:
    text = "On 2026-07-14 the reranker was disabled. " + ("Then filler. " * 300)

    out = condense_timeline_event(text, 40)

    assert "2026-07-14" in out
    assert "the reranker was disabled" in out
    assert len(out) < len(text)


def test_timeline_event_without_a_date_keeps_the_first_sentence() -> None:
    text = "The migration finished cleanly. " + ("Filler sentence. " * 300)

    out = condense_timeline_event(text, 40)

    assert out.startswith("The migration finished cleanly.")


def test_timeline_event_truncates_an_oversized_first_sentence() -> None:
    text = "word " * 2000 + ". tail."

    out = condense_timeline_event(text, 30)

    assert estimate_tokens(out) <= 30


# ── condense_code_block ───────────────────────────────────────────────


def test_code_block_keeps_signatures_and_drops_bodies() -> None:
    text = (
        "import os\n"
        "class Store:\n"
        "    def write(self, memory):\n"
        + "        intermediate_step()\n" * 200
        + "        return True\n"
    )

    out = condense_code_block(text, 60)

    assert "import os" in out
    assert "class Store:" in out
    assert "intermediate_step()" not in out


def test_code_block_without_signatures_falls_back_to_truncation() -> None:
    text = "value = compute(other)\n" * 300

    out = condense_code_block(text, 25)

    assert out
    assert estimate_tokens(out) <= 25


# ── condense_memory_content dispatch ──────────────────────────────────


def test_dispatch_returns_content_verbatim_when_it_fits() -> None:
    text = "small enough"

    assert condense_memory_content(text, FITS) == text


def test_code_tag_wins_over_content_shape() -> None:
    text = "import sys\n" + "plain prose sentence. " * 300

    out = condense_memory_content(text, 40, tags=["code"])

    assert out.startswith("import sys")


def test_timeline_tag_selects_the_event_condenser() -> None:
    text = "On 2026-01-02 it shipped. " + ("filler. " * 300)

    out = condense_memory_content(text, 40, tags=["timeline"])

    assert "2026-01-02" in out


def test_fenced_code_dispatches_to_the_assistant_condenser() -> None:
    text = ("prose. " * 200) + "\n```\nkeep_me()\n```\n" + ("prose. " * 200)

    out = condense_memory_content(text, 120)

    assert "keep_me()" in out


def test_arrow_dense_content_dispatches_to_triples() -> None:
    text = "a → b → c\nd -> e -> f\n" + "filler line without arrows\n" * 200

    out = condense_memory_content(text, 40)

    assert "a → b → c" in out
    assert "filler line" not in out


def test_cortex_transcript_format_dispatches_by_speaker() -> None:
    assistant = "[assistant]: Opening line. " + ("filler. " * 300)
    user = "[user]: Opening question? " + ("filler. " * 300)

    assistant_out = condense_memory_content(assistant, 40)
    user_out = condense_memory_content(user, 40)

    assert len(assistant_out) < len(assistant)
    assert user_out.startswith("[user]: Opening question?")


def test_plain_prose_defaults_to_the_user_condenser() -> None:
    text = "Opening statement. " + ("filler sentence. " * 300) + "Closing statement."

    out = condense_memory_content(text, 40)

    assert out.startswith("Opening statement.")
    assert out.endswith("Closing statement.")
