"""Mutation-hardening contract tests for condense_structured.py (issue #228).

A scoped mutmut run over the pre-split condensers.py left 9 survivors in
condense_entity_triples that no test in test_condensers.py could
distinguish. Each test below pins one such observable contract via an
exact-equality assertion.

Budgets are chosen so the arithmetic is exact: ``estimate_tokens`` is
``len(text) // 3``, so a text of ``3 * N`` characters is worth exactly
``N`` tokens and a boundary can be hit on the nose.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.condense_structured import (
    condense_entity_triples,
)

# Four 5-token triple lines behind one line that is not a triple.
TRIPLE_LINES = [f"aa{i} → bb{i} → cc{i}" for i in range(4)]
TRIPLE_TEXT = "Prose preamble line\n" + "\n".join(TRIPLE_LINES)


def test_entity_triples_at_exact_budget_is_returned_verbatim() -> None:
    assert estimate_tokens(TRIPLE_TEXT) == 27

    assert condense_entity_triples(TRIPLE_TEXT, 27) == TRIPLE_TEXT
    # One token tighter: the non-triple preamble is dropped.
    assert condense_entity_triples(TRIPLE_TEXT, 26) == "\n".join(TRIPLE_LINES)


def test_entity_triples_stop_at_the_budget_boundary() -> None:
    """Lines are admitted while ``used + t <= budget``, then the scan breaks.

    Budget 10 admits exactly two 5-token lines: the third would make 15.
    """
    out = condense_entity_triples(TRIPLE_TEXT, 10)

    assert out == "aa0 → bb0 → cc0\naa1 → bb1 → cc1"
