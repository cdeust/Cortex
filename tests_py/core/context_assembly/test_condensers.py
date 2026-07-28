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
    condense_assembled_context,
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
        + "More narrative filler that should not survive.\n"
        * 60
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


# ── condense_assembled_context ────────────────────────────────────────
#
# The wiring for issue #196: the missing caller that connects
# StageAwareContextAssembler's three raw phase outputs (own/adjacent/
# summaries — pg_recall.assemble_context) to decomposer.assemble_prompt's
# priority-condensation, so the combined context stays within the
# caller's token_budget even when each phase's independent sub-budget
# already fit but the sum did not.
#
# Postcondition (under budget): the result is byte-identical to
# StageAwareContextAssembler's own concatenation format — a strict
# no-op in the common case where per-phase budgeting already fits.


def test_assembled_context_under_budget_matches_stage_assembler_format() -> None:
    result = condense_assembled_context(
        "own content", "adjacent content", "summary content", "stage-1", 1000
    )
    assert result == (
        "## Current Stage Context (stage-1)\n\nown content\n\n"
        "## Related Prior Context\n\nadjacent content\n\n"
        "## Stage Summaries\n\nsummary content"
    )


def test_assembled_context_omits_empty_sections() -> None:
    result = condense_assembled_context("own only", "", "", "stage-1", 1000)
    assert result == "## Current Stage Context (stage-1)\n\nown only"
    assert "Related Prior Context" not in result
    assert "Stage Summaries" not in result


def test_assembled_context_all_empty_returns_empty_string() -> None:
    assert condense_assembled_context("", "", "", "stage-1", 1000) == ""


def test_assembled_context_whitespace_only_input_treated_as_empty() -> None:
    result = condense_assembled_context("  \n  ", "adjacent", "", "s", 1000)
    assert "Current Stage Context" not in result
    assert "adjacent" in result


def test_assembled_context_exactly_at_budget_is_not_condensed() -> None:
    own = "x" * 30  # estimate_tokens: 30 // 3 == 10
    budget = estimate_tokens(own)
    result = condense_assembled_context(own, "", "", "s", budget)
    assert result == f"## Current Stage Context (s)\n\n{own}"


# Postcondition (over budget): the result stays within budget (up to
# decomposer's fixed safety margin) and the higher-priority (own-stage)
# section survives with at least as large a share as lower-priority ones.


def test_assembled_context_over_budget_result_fits_within_budget() -> None:
    own = "This is the own stage context. " * 200
    adjacent = "This is adjacent context. " * 200
    summaries = "Summary line. " * 50
    budget = 300

    result = condense_assembled_context(own, adjacent, summaries, "s", budget)

    # decomposer's post-assembly safety loop enforces
    # context_window - safety_margin_tokens (default 64); with
    # headroom=1.0, context_window == token_budget.
    assert estimate_tokens(result) <= budget


def test_assembled_context_condensation_engages_and_reduces_content() -> None:
    # decomposer.assemble_prompt enforces a 300-token variable-budget
    # floor (`max(300, budget - shell_tokens)`) regardless of how small
    # token_budget is — that floor is decomposer.py's own pre-existing
    # invariant, out of this wiring's control. What THIS function is
    # responsible for is: route to assemble_prompt (not the fast
    # pass-through) and produce shorter content than the untouched
    # original when over budget.
    own = "y" * 3000  # ~1000 tokens
    result = condense_assembled_context(own, "", "", "s", 10)
    assert estimate_tokens(result) < estimate_tokens(own)


def test_assembled_context_own_stage_survives_more_than_summaries() -> None:
    own = "Own stage detail. " * 100
    adjacent = "Adjacent detail. " * 100
    summaries = "Summary detail. " * 100
    result = condense_assembled_context(own, adjacent, summaries, "s", 200)

    # own is priority 1 (protected longest); summaries priority 3
    # (condensed first / hardest). own's surviving span should be at
    # least as large as summaries' surviving span.
    assert result.find("Own stage detail.") != -1
    own_span = result.count("Own stage detail.")
    summary_span = result.count("Summary detail.")
    assert own_span >= summary_span


def test_assembled_context_emits_truncation_warning_banner() -> None:
    own = "word " * 2000
    result = condense_assembled_context(own, "", "", "s", 50)
    assert "CONTEXT TRUNCATION WARNING" in result


def test_assembled_context_over_budget_excludes_missing_sections() -> None:
    own = "word " * 2000
    result = condense_assembled_context(own, "", "", "s", 50)
    assert "Related Prior Context" not in result
    assert "Stage Summaries" not in result


# Mutation-hardening tests (issue #196, §12): each pins a contract facet
# a scoped mutmut run showed no earlier test could distinguish. Blob
# content ("x"*N) has no sentence/code structure, so every condenser
# falls back to deterministic truncation — the arithmetic below is exact.


def test_assembled_context_exactly_at_budget_is_byte_identical() -> None:
    # Boundary contract: total == token_budget takes the no-op fast path
    # and returns EXACTLY the header+concatenation — the condensation
    # path would trim via decomposer's safety margin and prepend
    # nothing-identical output. (Kills the `<=` → `<` boundary mutant.)
    own = "q" * 3000  # estimate_tokens == 1000
    result = condense_assembled_context(own, "", "", "s", 1000)
    assert result == f"## Current Stage Context (s)\n\n{own}"


def test_assembled_context_over_budget_condenses_every_section() -> None:
    # Three sections at 800/800/200 tokens against a 1300-token budget:
    # the documented postcondition ("each section is priority-condensed")
    # means ALL of them yield ground — own and summaries are both
    # reduced, and the banner names every section by its human-readable
    # placeholder key. This distinguishes headroom drift (a smaller
    # input budget over-trims and spares summaries; a larger one spares
    # own entirely) and any renamed/opaque banner label.
    own = "x" * 2400
    adjacent = "y" * 2400
    summaries = "z" * 600
    budget = 1300

    result = condense_assembled_context(own, adjacent, summaries, "s", budget)

    assert own not in result, "own-stage must participate in condensation"
    assert summaries not in result, "summaries must participate too"
    for key in ("{{OWN_STAGE}}", "{{ADJACENT_STAGE}}", "{{STAGE_SUMMARIES}}"):
        assert f"- {key}:" in result, f"banner must label {key} by its key"
    # Section order and the blank-line joiner survive condensation.
    assert "\n\n## Related Prior Context\n\n" in result
    assert "\n\n## Stage Summaries\n\n" in result


def test_assembled_context_adjacent_yields_budget_to_own_stage() -> None:
    # Priority contract, asymmetric sizes: own (800 tokens) vs adjacent
    # (300 tokens) against a 1000-token budget. Adjacent (priority 2) is
    # condensed first, so own ends with the strictly larger surviving
    # span and adjacent is the section that gets cut. A priority tie
    # (own demoted to adjacent's rank) flips who is processed first and
    # leaves adjacent fully intact instead.
    own = "x" * 2400  # 800 tokens
    adjacent = "y" * 900  # 300 tokens

    result = condense_assembled_context(own, adjacent, "", "s", 1000)

    assert adjacent not in result, "adjacent is the section that yields"
    assert result.count("x") > result.count("y"), "own survives larger"
