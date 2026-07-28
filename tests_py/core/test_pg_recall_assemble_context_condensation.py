"""Tests for pg_recall.assemble_context's condensation wiring (#196).

assemble_context() previously returned StageAwareContextAssembler's raw
``assembled_context`` unconditionally, even though each of its three
phases enforces only its OWN sub-budget independently — the combined
total can exceed the caller's ``token_budget``. This wires
``condense_assembled_context`` (context_assembly/condensers.py) as the
missing final truncation-awareness pass, matching the module's own
docstring promise: "a budgeted, slot-filled prompt with truncation
awareness."

These tests stub ``StageAwareContextAssembler.assemble`` directly (no
real store/embeddings/entity graph needed) so they isolate the wiring
in ``assemble_context`` from the phase-selection logic already covered
by other tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcp_server.core import pg_recall
from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.stage_assembler import StageContextResult


def _fake_result(own: str, adjacent: str, summaries: str) -> StageContextResult:
    parts = []
    if own:
        parts.append(f"## Current Stage Context (s1)\n\n{own}")
    if adjacent:
        parts.append(f"## Related Prior Context\n\n{adjacent}")
    if summaries:
        parts.append(f"## Stage Summaries\n\n{summaries}")
    return StageContextResult(
        own_stage_context=own,
        adjacent_stage_context=adjacent,
        stage_summaries=summaries,
        assembled_context="\n\n".join(parts),
        selected_memories=[],
        metadata={"total_tokens": estimate_tokens("\n\n".join(parts))},
    )


class TestAssembleContextCondensationWiring:
    def test_under_budget_result_unchanged(self):
        """Postcondition: when the raw assembled_context already fits
        token_budget, assemble_context's output is unchanged (the
        condense pass is a documented no-op in this case)."""
        fake = _fake_result("own text", "adjacent text", "summary text")
        with patch(
            "mcp_server.core.context_assembly.stage_assembler."
            "StageAwareContextAssembler.assemble",
            return_value=fake,
        ):
            result = pg_recall.assemble_context(
                query="q",
                store=MagicMock(),
                embeddings=MagicMock(),
                current_stage="s1",
                token_budget=1000,
            )
        assert result["assembled_context"] == fake.assembled_context

    def test_over_budget_result_is_condensed(self):
        """Postcondition: when the raw assembled_context exceeds
        token_budget, assemble_context's output is shorter than the
        raw concatenation and stays closer to the budget."""
        own = "own stage detail. " * 300
        adjacent = "adjacent detail. " * 300
        summaries = "summary detail. " * 300
        fake = _fake_result(own, adjacent, summaries)
        raw_tokens = estimate_tokens(fake.assembled_context)
        budget = 200
        assert raw_tokens > budget  # precondition of this test

        with patch(
            "mcp_server.core.context_assembly.stage_assembler."
            "StageAwareContextAssembler.assemble",
            return_value=fake,
        ):
            result = pg_recall.assemble_context(
                query="q",
                store=MagicMock(),
                embeddings=MagicMock(),
                current_stage="s1",
                token_budget=budget,
            )

        assert estimate_tokens(result["assembled_context"]) < raw_tokens
        # The separately-returned phase fields stay the RAW (uncondensed)
        # values — downstream evaluators match selected_memories against
        # these, so condensing them too would break that contract.
        assert result["own_stage_context"] == own
        assert result["adjacent_stage_context"] == adjacent
        assert result["stage_summaries"] == summaries

    def test_none_token_budget_skips_condensation(self):
        """Postcondition: when token_budget is None (stage_assembler's
        own 'no token truncation' mode), assemble_context must not
        invoke the condensation pass — nothing to condense against."""
        fake = _fake_result("own text", "adjacent text", "summary text")
        with (
            patch(
                "mcp_server.core.context_assembly.stage_assembler."
                "StageAwareContextAssembler.assemble",
                return_value=fake,
            ),
            patch(
                "mcp_server.core.context_assembly.condensers.condense_assembled_context"
            ) as mock_condense,
        ):
            result = pg_recall.assemble_context(
                query="q",
                store=MagicMock(),
                embeddings=MagicMock(),
                current_stage="s1",
                token_budget=None,
            )
        mock_condense.assert_not_called()
        assert result["assembled_context"] == fake.assembled_context
