"""Tests for core/context_assembly/stage_assembler — 3-phase assembly.

The assembler's stated contract is that a token budget "may truncate
individual chunks but never reduces the count of selected items".
``test_budget_never_drops_an_adjacent_memory`` is the regression test
for #196: before the condensers were wired, Phase 2 skipped any memory
that did not fit the remaining budget, so a long memory disappeared
from both the text and the retrieval record.

All external lookups are injected fakes — this module is pure.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.stage_assembler import (
    BudgetSplit,
    StageAwareContextAssembler,
    _join_sections,
)
from mcp_server.core.context_assembly.stage_detector import ExplicitStageDetector

LONG = "This is one sentence of a long memory. " * 60


def _memory(mid: int, stage: str, content: str, entity_ids: list[str]) -> dict:
    return {
        "memory_id": mid,
        "content": content,
        "score": 1.0 / mid,
        "plan_id": stage,
        "entity_ids": entity_ids,
    }


def _assembler(
    *,
    own: list[dict],
    adjacent: list[dict],
    summaries: dict[str, str] | None = None,
    all_stages: list[str] | None = None,
) -> StageAwareContextAssembler:
    """Wire the assembler to fixed in-memory fakes."""
    entities = [{"id": "e1", "name": "store"}, {"id": "e2", "name": "recall"}]
    relationships = [
        {"source_entity_id": "e1", "target_entity_id": "e2", "strength": 1.0}
    ]

    detector = ExplicitStageDetector(field="plan_id")
    if all_stages is not None:
        detector.all_stages = lambda corpus: list(all_stages)  # type: ignore[method-assign]

    return StageAwareContextAssembler(
        stage_detector=detector,
        retrieve_fn=lambda query, stage, limit: list(own),
        entity_graph_fn=lambda: (entities, relationships),
        memories_by_entity_fn=lambda ids: list(adjacent),
        stage_summary_fn=lambda stage: (summaries or {}).get(stage, ""),
    )


# ── The #196 regression ───────────────────────────────────────────────


def test_budget_never_drops_an_adjacent_memory() -> None:
    own = [_memory(1, "s1", "short own memory", ["e1"])]
    adjacent = [
        _memory(2, "s2", LONG, ["e1", "e2"]),
        _memory(3, "s3", LONG, ["e2"]),
    ]

    result = _assembler(own=own, adjacent=adjacent).assemble(
        query="q", current_stage="s1", token_budget=120
    )

    phase2_ids = [m["memory_id"] for m in result.selected_memories if m["phase"] == 2]
    assert phase2_ids == [2, 3], "both adjacent memories must survive the budget"
    assert result.adjacent_stage_context, "phase 2 text must not be empty"


def test_selected_records_carry_full_content_under_a_budget() -> None:
    own = [_memory(1, "s1", LONG, ["e1"])]

    result = _assembler(own=own, adjacent=[]).assemble(
        query="q", current_stage="s1", token_budget=60
    )

    assert result.selected_memories[0]["content"] == LONG
    assert len(result.own_stage_context) < len(LONG)


def test_no_budget_reproduces_verbatim_content() -> None:
    own = [_memory(1, "s1", LONG, ["e1"])]

    result = _assembler(own=own, adjacent=[]).assemble(
        query="q", current_stage="s1", token_budget=None
    )

    assert LONG.strip() in result.own_stage_context


# ── Phase composition ─────────────────────────────────────────────────


def test_absent_entities_skip_phase_two_entirely() -> None:
    own = [_memory(1, "s1", "no entities here", [])]

    result = _assembler(own=own, adjacent=[_memory(2, "s2", "unreachable", ["e1"])])
    out = result.assemble(query="q", current_stage="s1", token_budget=None)

    assert out.adjacent_stage_context == ""
    assert out.metadata["adjacent_stages"] == []
    assert all(m["phase"] == 1 for m in out.selected_memories)


def test_summaries_cover_only_the_stages_phases_one_and_two_missed() -> None:
    own = [_memory(1, "s1", "own", ["e1"])]
    adjacent = [_memory(2, "s2", "adjacent", ["e1"])]

    out = _assembler(
        own=own,
        adjacent=adjacent,
        summaries={"s3": "third stage summary", "s2": "should not appear"},
        all_stages=["s1", "s2", "s3"],
    ).assemble(query="q", current_stage="s1", token_budget=None)

    assert out.metadata["summary_stages"] == ["s3"]
    assert "third stage summary" in out.stage_summaries
    assert "should not appear" not in out.stage_summaries


def test_metadata_reports_the_budget_it_was_given() -> None:
    own = [_memory(1, "s1", "own", ["e1"])]

    out = _assembler(own=own, adjacent=[]).assemble(
        query="q",
        current_stage="s1",
        token_budget=900,
        budget_split=BudgetSplit(own_stage=0.5, adjacent=0.4, summaries=0.1),
    )

    assert out.metadata["token_budget"] == 900
    assert out.metadata["budget_split"] == (0.5, 0.4, 0.1)
    assert out.metadata["own_stage_chunks"] == 1
    assert out.metadata["total_tokens"] == (
        out.metadata["own_stage_tokens"]
        + out.metadata["adjacent_tokens"]
        + out.metadata["summary_tokens"]
    )


def test_budget_split_must_sum_to_one() -> None:
    import pytest

    with pytest.raises(ValueError, match="must sum to 1.0"):
        BudgetSplit(own_stage=0.5, adjacent=0.4, summaries=0.4)


# ── Section joining ───────────────────────────────────────────────────


def test_only_non_empty_sections_get_a_header() -> None:
    joined = _join_sections("s1", "own text", "", "summary text")

    assert "## Current Stage Context (s1)" in joined
    assert "## Related Prior Context" not in joined
    assert "## Stage Summaries" in joined


def test_all_sections_empty_yields_empty_context() -> None:
    assert _join_sections("s1", "", "", "") == ""
