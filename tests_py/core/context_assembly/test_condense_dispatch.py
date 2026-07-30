"""Mutation-hardening dispatch tests for condense_dispatch.py (issue #228).

A scoped mutmut run over the pre-split condensers.py left 25 survivors in
condense_memory_content that no test in test_condensers.py could
distinguish — the routing decision itself (which tag matches, which
content shape wins, which speaker prefix is recognised), not any single
condenser's internal arithmetic.

Each test asserts the EXACT output of the condenser the dispatcher is
expected to route to, because every route ultimately returns a shortened
string: a substring assertion cannot tell "routed to the code condenser"
apart from "fell through to the prose condenser, which happened to keep
the same opening".
"""

from __future__ import annotations

from mcp_server.core.context_assembly.condense_dispatch import condense_memory_content

# Indented code whose 4-space runs would route it to the assistant
# condenser on shape alone — so a tag that fails to match is visible.
TAGGED_CODE = "import sys\ndef go():\n" + "    body()\n" * 200 + "final_call()\n"
TAGGED_CODE_CONDENSED = "import sys\ndef go():"

TAGGED_EVENT = "On 2026-01-02 it shipped. " + "filler. " * 300
TAGGED_EVENT_CONDENSED = "[2026-01-02] On 2026-01-02 it shipped."

# Three sentences, one of them pure filler: condensing drops the middle.
THREE_SENTENCES = "One. Two. Three."
THREE_SENTENCES_TOKENS = 5  # len == 16, 16 // 3 == 5

_ARROW_FILLER = "prose filler line\n" * 80


def test_memory_content_at_exact_budget_is_returned_verbatim() -> None:
    assert condense_memory_content(THREE_SENTENCES, THREE_SENTENCES_TOKENS) == (
        THREE_SENTENCES
    )
    assert condense_memory_content(THREE_SENTENCES, 4) == "One. Three."


def test_code_tag_routes_to_the_code_block_condenser() -> None:
    assert condense_memory_content(TAGGED_CODE, 40, tags=["code"]) == (
        TAGGED_CODE_CONDENSED
    )


def test_file_tag_routes_to_the_code_block_condenser() -> None:
    """``file`` is the second arm of the same ``or`` — it must match alone."""
    assert condense_memory_content(TAGGED_CODE, 40, tags=["file"]) == (
        TAGGED_CODE_CONDENSED
    )


def test_timeline_tag_routes_to_the_timeline_condenser() -> None:
    assert condense_memory_content(TAGGED_EVENT, 40, tags=["timeline"]) == (
        TAGGED_EVENT_CONDENSED
    )


def test_event_tag_routes_to_the_timeline_condenser() -> None:
    """``event`` is the second arm of the same ``or`` — it must match alone."""
    assert condense_memory_content(TAGGED_EVENT, 40, tags=["event"]) == (
        TAGGED_EVENT_CONDENSED
    )


def test_two_unicode_arrows_reach_the_triple_threshold() -> None:
    """Exactly two "→" and no "->" is on the threshold, inclusive."""
    content = "alpha → beta → gamma\n" + _ARROW_FILLER
    assert (content.count("→"), content.count("->")) == (2, 0)

    assert condense_memory_content(content, 20) == "alpha → beta → gamma"


def test_two_ascii_arrows_reach_the_triple_threshold() -> None:
    """The ASCII "->" spelling is counted into the same threshold."""
    content = "alpha -> beta -> gamma\n" + _ARROW_FILLER
    assert (content.count("→"), content.count("->")) == (0, 2)

    assert condense_memory_content(content, 20) == "alpha -> beta -> gamma"


def test_assistant_prefixed_transcript_routes_to_the_assistant_condenser() -> None:
    """The speaker prefix is read after ``lstrip()``, and matched exactly.

    The assistant condenser keeps only the leading sentence; the user
    condenser would append the closing sentence too, so the two routes
    are distinguishable on this input.
    """
    content = (
        "  \n[assistant]: Opening line. " + "Filler sentence. " * 60 + "Closing line."
    )

    assert condense_memory_content(content, 40) == "[assistant]: Opening line."


def test_user_prefixed_transcript_naming_the_assistant_routes_to_assistant() -> None:
    """A ``[user]:`` opener that later names the assistant uses that branch."""
    content = (
        "  \n[user]: Opening question. [assistant]: Answer line. "
        + "Filler sentence. " * 60
        + "Closing line."
    )

    assert condense_memory_content(content, 40) == "[user]: Opening question."


def test_indent_runs_alone_route_to_the_assistant_condenser() -> None:
    """Shape dispatch fires on indentation even with no fence present."""
    content = "Head line.\n" + "    a()\n" * 3 + "Filler prose sentence. " * 100
    assert content.count("    ") == 3

    assert condense_memory_content(content, 60) == "Head line."
