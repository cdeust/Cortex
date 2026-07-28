"""Direct tests for mcp_server.core.context_assembly.decomposer and the
budget.py primitives it depends on (#196). condense_assembled_context's
tests only exercise assemble_prompt's over-budget path; these close the
fast-path and truncate-fallback branches directly.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import (
    AssemblyMetrics,
    Placeholder,
    available_budget,
    estimate_tokens,
    truncate_to_budget,
)
from mcp_server.core.context_assembly.decomposer import assemble_prompt


class TestAssemblyMetrics:
    def test_reduction_fraction_zero_original_is_full(self):
        metrics = AssemblyMetrics()
        assert metrics.reduction_fraction("{{A}}") == 1.0

    def test_reduction_fraction_computes_ratio(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 50}
        )
        assert metrics.reduction_fraction("{{A}}") == 0.5

    def test_was_truncated_true_below_threshold(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 50}
        )
        assert metrics.was_truncated("{{A}}") is True

    def test_was_truncated_false_above_threshold(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 95}
        )
        assert metrics.was_truncated("{{A}}") is False


class TestEstimateTokens:
    def test_empty_string_is_zero(self):
        assert estimate_tokens("") == 0

    def test_minimum_one_token_for_nonempty(self):
        assert estimate_tokens("a") == 1

    def test_roughly_chars_over_three(self):
        assert estimate_tokens("x" * 30) == 10


class TestAvailableBudget:
    def test_zero_context_window_returns_zero(self):
        assert available_budget(0) == 0

    def test_negative_context_window_returns_zero(self):
        assert available_budget(-100) == 0

    def test_default_headroom_is_75_percent(self):
        assert available_budget(1000) == 750

    def test_custom_headroom(self):
        assert available_budget(1000, headroom=1.0) == 1000


class TestTruncateToBudget:
    def test_within_budget_returned_unchanged(self):
        text = "short"
        assert truncate_to_budget(text, 1000) == text

    def test_truncates_at_line_boundary(self):
        text = "line one\nline two\nline three\n" + ("x" * 100)
        result = truncate_to_budget(text, 5)
        assert result.endswith("\n") or "\n" not in result

    def test_falls_back_to_hard_cut_without_newline(self):
        text = "x" * 1000
        result = truncate_to_budget(text, 3)
        assert len(result) <= 9  # target_chars = 3*3 = 9, no newline found
        assert result == text[:9]


class TestAssemblePromptFastPath:
    def test_content_fitting_budget_used_verbatim(self):
        placeholders = [Placeholder("{{A}}", "short content", priority=1)]
        prompt, metrics = assemble_prompt(
            "prefix {{A}} suffix", placeholders, context_window=10000
        )
        assert "short content" in prompt
        assert metrics.final_tokens["{{A}}"] == metrics.original_tokens["{{A}}"]

    def test_multiple_placeholders_all_fit(self):
        placeholders = [
            Placeholder("{{A}}", "content a", priority=1),
            Placeholder("{{B}}", "content b", priority=2),
        ]
        prompt, _metrics = assemble_prompt(
            "{{A}} - {{B}}", placeholders, context_window=10000
        )
        assert "content a" in prompt
        assert "content b" in prompt

    def test_no_banner_when_nothing_truncated(self):
        placeholders = [Placeholder("{{A}}", "fits fine", priority=1)]
        prompt, _metrics = assemble_prompt("{{A}}", placeholders, context_window=10000)
        assert "TRUNCATION WARNING" not in prompt


class TestAssemblePromptCondensation:
    def test_placeholder_within_share_kept_full(self):
        # Two placeholders, one tiny (fits its share), one huge (doesn't).
        placeholders = [
            Placeholder("{{SMALL}}", "x" * 30, priority=1),
            Placeholder("{{BIG}}", "y" * 3000, priority=2),
        ]
        prompt, metrics = assemble_prompt(
            "{{SMALL}} {{BIG}}", placeholders, context_window=300, headroom=1.0
        )
        assert metrics.final_tokens["{{SMALL}}"] == metrics.original_tokens["{{SMALL}}"]

    def test_placeholder_without_condenser_falls_back_to_truncate(self):
        placeholders = [Placeholder("{{A}}", "z" * 3000, priority=1, condenser=None)]
        prompt, _metrics = assemble_prompt(
            "{{A}}", placeholders, context_window=100, headroom=1.0
        )
        assert estimate_tokens(prompt) < estimate_tokens("z" * 3000)

    def test_placeholder_with_condenser_uses_it(self):
        calls = []

        def fake_condenser(value: str, budget: int) -> str:
            calls.append((value, budget))
            return "condensed"

        placeholders = [
            Placeholder("{{A}}", "x" * 3000, priority=1, condenser=fake_condenser)
        ]
        prompt, _metrics = assemble_prompt(
            "{{A}}", placeholders, context_window=100, headroom=1.0
        )
        assert calls  # condenser was invoked
        assert "condensed" in prompt


class TestAssemblePromptSafetyLoop:
    def test_halving_without_newline_falls_back_to_prefix(self):
        # A single, huge, no-newline placeholder forces the post-assembly
        # safety loop's halving branch with no '\n' to anchor on
        # (last_newline == -1, not > 0 → halved = prefix).
        placeholders = [Placeholder("{{A}}", "z" * 5000, priority=1, condenser=None)]
        prompt, metrics = assemble_prompt(
            "{{A}}", placeholders, context_window=80, safety_margin_tokens=64
        )
        # The safety loop's target (context_window - safety_margin) is
        # tiny; content must have been repeatedly halved.
        assert estimate_tokens(prompt) < estimate_tokens("z" * 5000)

    def test_halving_with_newline_cuts_at_line_boundary(self):
        # A placeholder whose first-half slice DOES contain a newline
        # exercises the other halving branch (halved = val[:last_newline+1]).
        placeholders = [
            Placeholder(
                "{{A}}", ("line of text here\n" * 500), priority=1, condenser=None
            )
        ]
        prompt, _metrics = assemble_prompt(
            "{{A}}", placeholders, context_window=80, safety_margin_tokens=64
        )
        assert estimate_tokens(prompt) < estimate_tokens("line of text here\n" * 500)

    def test_safety_loop_stops_when_nothing_left_to_trim(self):
        # All placeholders already at/below the 50-token halving floor —
        # the loop must terminate via `did_trim = False`, not iterate
        # forever.
        placeholders = [Placeholder("{{A}}", "short", priority=1)]
        prompt, _metrics = assemble_prompt(
            "{{A}}", placeholders, context_window=1, safety_margin_tokens=0
        )
        assert isinstance(prompt, str)
