"""Tests for core/context_assembly/stage_phases — condense, never drop.

The contract these pin is the one the assembler documents and, before
#196, violated: under a token budget every selected item still reaches
the rendered text. A phase that skipped over-budget items silently
deleted the longest memories — the ones retrieval had just ranked
highest — and made the selected-item count depend on memory length.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import (
    MIN_ITEM_SHARE_TOKENS,
    estimate_tokens,
)
from mcp_server.core.context_assembly.stage_phases import (
    pack_within_budget,
    phase_budget,
    render_adjacent,
    render_own_stage,
    render_summaries,
)


def _mem(content: str, **extra) -> dict:
    return {"content": content, **extra}


# ── pack_within_budget ────────────────────────────────────────────────


def test_every_item_survives_a_budget_far_below_its_size() -> None:
    memories = [_mem("word " * 400) for _ in range(5)]

    texts, _ = pack_within_budget(memories, 60)

    assert len(texts) == len(memories)
    assert all(t for t in texts), "no item may render as empty text"


def test_item_that_fits_its_share_is_verbatim() -> None:
    memories = [_mem("short memory"), _mem("another short one")]

    texts, used = pack_within_budget(memories, 1000)

    assert texts == ["short memory", "another short one"]
    assert used == sum(estimate_tokens(t) for t in texts)


def test_over_share_item_is_condensed_not_truncated_to_nothing() -> None:
    long_content = "First sentence. " + ("filler sentence. " * 200) + "Last one."

    texts, _ = pack_within_budget([_mem(long_content)], 80)

    assert len(texts[0]) < len(long_content)
    assert texts[0].startswith("First sentence.")


def test_zero_budget_still_renders_every_item() -> None:
    memories = [_mem("a" * 900), _mem("b" * 900)]

    texts, used = pack_within_budget(memories, 0)

    assert len(texts) == 2
    # The floor binds: each item gets MIN_ITEM_SHARE_TOKENS, never zero.
    assert used <= 2 * MIN_ITEM_SHARE_TOKENS


def test_output_stays_within_the_documented_ceiling() -> None:
    memories = [_mem("word " * 300) for _ in range(4)]
    budget = 500

    _, used = pack_within_budget(memories, budget)

    assert used <= max(budget, len(memories) * MIN_ITEM_SHARE_TOKENS)


def test_none_budget_returns_content_verbatim() -> None:
    memories = [_mem("x" * 5000), _mem("y" * 5000)]

    texts, used = pack_within_budget(memories, None)

    assert texts == ["x" * 5000, "y" * 5000]
    assert used == sum(estimate_tokens(t) for t in texts)


def test_code_tag_routes_to_the_code_condenser() -> None:
    code = "```python\n" + "call_me()\n" * 200 + "```\n" + ("prose. " * 200)

    texts, _ = pack_within_budget([_mem(code, tags=["code"])], 100)

    assert "call_me()" in texts[0]


def test_malformed_tags_do_not_raise() -> None:
    texts, _ = pack_within_budget([_mem("word " * 300, tags="notalist")], 40)

    assert len(texts) == 1


def test_missing_content_key_renders_empty_string() -> None:
    texts, used = pack_within_budget([{"memory_id": 7}], 100)

    assert texts == [""]
    assert used == 0


# ── phase_budget ──────────────────────────────────────────────────────


def test_phase_budget_splits_the_total() -> None:
    assert phase_budget(1000, 0.6) == 600


def test_phase_budget_propagates_none() -> None:
    assert phase_budget(None, 0.6) is None


# ── render_own_stage ──────────────────────────────────────────────────


def test_records_keep_original_content_when_text_is_condensed() -> None:
    original = "sentence one. " + ("filler. " * 300)
    selected = [{"memory_id": 42, "content": original, "score": 0.9}]

    text, _, records = render_own_stage(selected, 60)

    assert len(text) < len(original)
    assert records[0]["content"] == original, (
        "the retrieval record must stay verbatim — evaluators score against it"
    )
    assert records[0] == {
        "memory_id": 42,
        "content": original,
        "score": 0.9,
        "phase": 1,
    }


def test_own_stage_joins_items_with_a_blank_line() -> None:
    text, _, _ = render_own_stage([_mem("alpha"), _mem("beta")], None)

    assert text == "alpha\n\nbeta"


# ── render_adjacent ───────────────────────────────────────────────────


def test_adjacent_keeps_only_the_top_scored_chunks() -> None:
    scored = [({"id": i, "content": f"m{i}"}, 1.0 / (i + 1)) for i in range(6)]

    text, _, records = render_adjacent(scored, None, 2)

    assert [r["memory_id"] for r in records] == [0, 1]
    assert text == "m0\n\nm1"
    assert all(r["phase"] == 2 for r in records)


def test_adjacent_records_prefer_memory_id_over_id() -> None:
    scored = [({"id": 1, "memory_id": 99, "content": "c"}, 0.5)]

    _, _, records = render_adjacent(scored, None, 5)

    assert records[0]["memory_id"] == 99


# ── render_summaries ──────────────────────────────────────────────────


def test_summaries_are_labelled_with_their_stage() -> None:
    text, _, stages = render_summaries([("plan-1", "did the thing")], None)

    assert text == "[plan-1] did the thing"
    assert stages == ["plan-1"]


def test_summaries_report_every_stage_that_reached_the_output() -> None:
    pairs = [("s1", "one " * 400), ("s2", "two " * 400)]

    text, _, stages = render_summaries(pairs, 40)

    assert stages == ["s1", "s2"], "a tight budget condenses, it does not drop stages"
    assert "[s1]" in text and "[s2]" in text
