"""Recency-truncation invariant for Condition A (protocol §2.A, §11.2).

The load-bearing anti-cheating choice: when the conversation exceeds the
model's input budget, KEEP THE LATEST tokens (recency truncation),
DROP the earliest. Implementing it the other way around would silently
favour Cortex (since the gold-supporting turns are often near the end
of the conversation).
"""

from __future__ import annotations

from benchmarks.llm_head_to_head.data_loader import BeamItem
from benchmarks.llm_head_to_head.long_context_truncator import (
    MODEL_INPUT_BUDGETS,
    build_naive_long_context,
    input_budget_for,
)


def _make_item(turn_count: int, tag_format: str = "TURN_{i:04d}") -> BeamItem:
    """Build a synthetic BeamItem with N distinct turns.

    Each turn's content is unique so we can identify which turns were
    kept. Word-count-controlled so the heuristic tokenizer is predictable.
    """
    turns = [
        {
            "id": i,
            "role": "user" if i % 2 == 0 else "assistant",
            "content": tag_format.format(i=i)
            + " "
            + " ".join(["filler"] * 40),  # ~40 words each
            "time_anchor": "",
            "plan_id": "",
        }
        for i in range(turn_count)
    ]
    return BeamItem(
        question_id="synthetic-trunc-test",
        conversation_idx=0,
        ability="information_extraction",
        question="?",
        gold_answer="",
        source_chat_ids=tuple(),
        turns=turns,
    )


def test_full_conversation_fits_no_truncation():
    """When the budget is large enough, return everything verbatim."""
    item = _make_item(10)
    result = build_naive_long_context(item, input_token_budget=10_000)
    assert not result.truncated
    # Every turn tag must appear.
    for i in range(10):
        assert f"TURN_{i:04d}" in result.text


def test_truncation_keeps_latest_drops_earliest():
    """Recency invariant: when budget is small, the LATEST turns survive.

    Build a 100-turn conversation, set a budget that holds maybe 5 turns,
    and assert TURN_0099 is present, TURN_0000 is NOT.
    """
    item = _make_item(100)
    # Each turn ~ (1 tag + 40 filler) words ≈ 55 tokens with 1.33 ratio.
    # Budget 300 tokens ≈ 5 turns.
    result = build_naive_long_context(item, input_token_budget=300)
    assert result.truncated, "Expected truncation at this budget"
    # Most recent turn MUST be present.
    assert "TURN_0099" in result.text, (
        "Recency-truncation broken: latest turn dropped. "
        "Protocol §11.2 requires keeping the latest tokens."
    )
    # Earliest turns MUST be dropped.
    assert "TURN_0000" not in result.text, (
        "Recency-truncation broken: earliest turn kept. "
        "Truncation must drop FROM THE HEAD, not from the tail."
    )


def test_truncation_returns_contiguous_suffix():
    """Recency-truncation produces a contiguous suffix; no gaps."""
    item = _make_item(50)
    result = build_naive_long_context(item, input_token_budget=500)
    if not result.truncated:
        return  # not interesting

    # Find which TURN_xxxx tags are in the result.
    present = sorted(i for i in range(50) if f"TURN_{i:04d}" in result.text)
    if not present:
        return
    # The set of present turns must form an unbroken suffix [k, k+1, ..., 49].
    expected_suffix = list(range(present[0], 50))
    assert present == expected_suffix, (
        f"Recency-truncation must return a contiguous suffix; "
        f"got non-contiguous turns: {present[:10]}..."
    )


def test_token_count_under_budget():
    """Final text token count ≤ budget (the postcondition)."""
    item = _make_item(200)
    budget = 1_000
    result = build_naive_long_context(item, input_token_budget=budget)
    assert result.input_tokens <= budget, (
        f"Truncated text exceeds budget: {result.input_tokens} > {budget}"
    )


def test_budget_lookup_for_known_models():
    """Pinned model IDs must have known budgets (protocol §2.A)."""
    for model_id, expected in MODEL_INPUT_BUDGETS.items():
        assert input_budget_for(model_id) == expected
        assert expected > 0


def test_budget_lookup_unknown_model_errors():
    """Unknown pins must raise — protocol freeze requires explicit pins."""
    import pytest

    with pytest.raises(KeyError):
        input_budget_for("not-a-real-model-id")
