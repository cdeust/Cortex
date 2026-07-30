"""Mutation-hardening contract tests for condense_code.py (issue #228).

A scoped mutmut run over the pre-split condensers.py left survivors in
condense_code_block (29), condense_assistant_message (28), and the three
fence-splitting helpers (7) that no test in test_condensers.py could
distinguish. Each test below pins one such observable contract via an
exact-equality assertion — the survivors were precisely the mutants a
substring/`in` assertion cannot see.

Budgets are chosen so the arithmetic is exact: ``estimate_tokens`` is
``len(text) // 3``, so a text of ``3 * N`` characters is worth exactly
``N`` tokens and a boundary can be hit on the nose.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.condense_code import (
    _has_code_blocks,
    _split_by_code_blocks,
    condense_assistant_message,
    condense_code_block,
)

# ── condense_assistant_message ────────────────────────────────────────

# Four fenced blocks worth 3 tokens each; the "```" line closing one block
# and opening the next is the 1-token prose segment between them.
FOUR_BLOCKS = "\n".join(f"```\nblk_{i}()\n```" for i in range(4))
FOUR_BLOCKS_CODE_TOKENS = 12

# Three fenced blocks separated by prose whose first sentences are all
# longer than 80 characters, so every slice length below is observable.
_PROSE = (
    "Prose {n} opening sentence padded out to well beyond "
    "sixty-three characters long. Prose {n} tail."
)
INTERLEAVED = "\n".join(
    [
        _PROSE.format(n="one"),
        "```",
        "c_one()",
        "```",
        _PROSE.format(n="two"),
        "```",
        "c_two()",
        "```",
        _PROSE.format(n="three"),
        "```",
        "c_three()",
        "```",
        _PROSE.format(n="four"),
    ]
)


def test_assistant_message_at_exact_budget_is_returned_verbatim() -> None:
    text = "Alpha sentence. Beta sentence."  # 30 chars -> 10 tokens
    assert estimate_tokens(text) == 10

    assert condense_assistant_message(text, 10) == text
    assert condense_assistant_message(text, 9) == "Alpha sentence."


def test_assistant_code_only_path_stops_at_the_budget_boundary() -> None:
    """Blocks are admitted while ``used + t <= budget``, then dropped.

    Budget 6 admits exactly two 3-token blocks: the third would make 9.
    """
    out = condense_assistant_message(FOUR_BLOCKS, 6)

    assert out == "```\nblk_0()\n\n```\nblk_1()"


def test_assistant_code_equal_to_budget_takes_the_code_only_path() -> None:
    """``code_tokens >= token_budget`` is inclusive: equality keeps code only.

    At the boundary the prose path would instead interleave the bare "```"
    separator segments between the blocks.
    """
    assert (
        sum(
            estimate_tokens(p)
            for is_code, p in _split_by_code_blocks(FOUR_BLOCKS)
            if is_code
        )
        == FOUR_BLOCKS_CODE_TOKENS
    )

    out = condense_assistant_message(FOUR_BLOCKS, FOUR_BLOCKS_CODE_TOKENS)

    assert out == "```\nblk_0()\n\n```\nblk_1()\n\n```\nblk_2()\n\n```\nblk_3()"


def test_assistant_interleaves_prose_and_code_in_original_order() -> None:
    """Every block and every compressed prose part lands in source order.

    Budget 60 leaves 50 prose tokens over 4 prose parts (12 each), so the
    ``max(20, ...)`` floor binds and each prose part is cut to 20 * 3 chars.
    """
    out = condense_assistant_message(INTERLEAVED, 60)

    assert out == (
        "Prose one opening sentence padded out to well beyond sixty-t"
        "\n\n```\nc_one()"
        "\n\n```\nProse two opening sentence padded out to well beyond six"
        "\n\n```\nc_two()"
        "\n\n```\nProse three opening sentence padded out to well beyond s"
        "\n\n```\nc_three()"
        "\n\n```\nProse four opening sentence padded out to well beyond si"
    )


def test_assistant_prose_share_scales_with_the_leftover_budget() -> None:
    """Above the floor, the prose slice tracks ``budget - code_tokens``.

    Budget 100 leaves 90 prose tokens over 4 parts (22 each), lifting the
    result off the ``max(20, ...)`` floor exercised by the test above.
    """
    out = condense_assistant_message(INTERLEAVED, 100)

    assert out == (
        "Prose one opening sentence padded out to well beyond sixty-three c"
        "\n\n```\nc_one()"
        "\n\n```\nProse two opening sentence padded out to well beyond sixty-thr"
        "\n\n```\nc_two()"
        "\n\n```\nProse three opening sentence padded out to well beyond sixty-t"
        "\n\n```\nc_three()"
        "\n\n```\nProse four opening sentence padded out to well beyond sixty-th"
    )


def test_assistant_blank_only_content_falls_back_to_truncation() -> None:
    """When every reassembled part is blank, the raw text is truncated.

    This is the only route to that fallback: the ``if s.strip()`` filter
    empties the join, and returning "" would delete the memory outright.
    """
    out = condense_assistant_message(" " * 300, 10)

    assert out == " " * 30


def test_assistant_unclosed_fence_is_a_single_code_segment() -> None:
    """Pins half (b) of the invariant that made the old fallback dead code.

    ``prose_parts`` can only be empty when the whole text is ONE code
    segment, which happens only for an unclosed fence — and then
    ``code_tokens == estimate_tokens(text)``, which the over-budget guard
    at the top of the function has already established exceeds the budget.
    So ``code_tokens >= token_budget`` always returns first (see the
    dead-code-removal rationale in ``condense_code.py``).
    """
    text = "```\n" + "step()\n" * 10

    assert _split_by_code_blocks(text) == [(True, text)]
    assert sum(estimate_tokens(p) for _is_code, p in [(True, text)]) == (
        estimate_tokens(text)
    )
    # Budget 10 < 24 tokens: the single block cannot be kept, so the
    # code-only branch degrades to generic truncation rather than "".
    assert condense_assistant_message(text, 10) == "```\nstep()\nstep()\nstep()\n"


# ── condense_code_block ───────────────────────────────────────────────

# One line per declared signature prefix, plus a blank line (which must be
# skipped, not treated as end-of-scan) and a body that must be dropped.
SIGNATURE_LINES = [
    "import os",
    "",
    "from x import y",
    "class C:",
    "def f():",
    "async def g():",
    "struct S {",
    "enum E {",
    "protocol P {",
    "func h() {",
    "interface I {",
    "@decorator",
    "// c-comment",
    "# py-comment",
]
SIGNATURE_SOURCE = "\n".join(SIGNATURE_LINES + ["    body_statement()"] * 40)

# Four 3-token signature lines with non-signature bodies between them.
SIGNATURE_ACCOUNTING = "\n".join(f"def a{i}():\n    x()" for i in range(1, 5))


def test_code_block_at_exact_budget_is_returned_verbatim() -> None:
    assert estimate_tokens(SIGNATURE_ACCOUNTING) == 23

    assert condense_code_block(SIGNATURE_ACCOUNTING, 23) == SIGNATURE_ACCOUNTING
    assert condense_code_block(SIGNATURE_ACCOUNTING, 22) == (
        "def a1():\ndef a2():\ndef a3():\ndef a4():"
    )


def test_code_block_keeps_every_declared_signature_prefix() -> None:
    """Each of the 13 prefixes is recognised, and a blank line is skipped.

    A budget of 200 is far above the 43 tokens the signatures cost, so
    nothing here is a budget effect: any missing line means its prefix
    stopped matching, and a truncated result means the blank line ended
    the scan instead of being skipped.
    """
    out = condense_code_block(SIGNATURE_SOURCE, 200)

    assert out == "\n".join(line for line in SIGNATURE_LINES if line)
    assert "body_statement()" not in out


def test_code_block_signature_accounting_stops_at_the_budget_boundary() -> None:
    """Signatures are admitted while ``used + t <= budget``, then dropped.

    Budget 6 admits exactly two 3-token signatures: the third would make 9.
    """
    out = condense_code_block(SIGNATURE_ACCOUNTING, 6)

    assert out == "def a1():\ndef a2():"


# ── helpers ───────────────────────────────────────────────────────────


def test_split_by_code_blocks_segments_preserve_original_newlines() -> None:
    """Segments are joined with a bare newline and flagged False/True.

    The fence line that closes a block is emitted into the FOLLOWING
    segment — the property that makes a prose segment exist between any
    two code segments (see the invariant in ``condense_assistant_message``).
    """
    text = "Prose one.\nProse two.\n```\ncode_a()\ncode_b()\n```\nTail one.\nTail two."

    assert _split_by_code_blocks(text) == [
        (False, "Prose one.\nProse two."),
        (True, "```\ncode_a()\ncode_b()"),
        (False, "```\nTail one.\nTail two."),
    ]


def test_has_code_blocks_indent_run_threshold_is_three() -> None:
    """Three 4-space runs is code; two is not. The comparison is inclusive."""
    assert _has_code_blocks("x" + "    " * 3) is True
    assert _has_code_blocks("x" + "    " * 2) is False


def test_has_code_blocks_detects_a_fence() -> None:
    assert _has_code_blocks("```") is True
    assert _has_code_blocks("plain prose") is False
