"""Three-phase stage-aware context assembler.

Ports Clément Deust's Swift `StageAwareContextAssembler` from
ai-architect-prd-builder/packages/AIPRDRAGEngine/Sources/Services/
StageAwareContextAssembler.swift to Python, adapted for Cortex's
memory types and complemented with paper-backed mechanisms at three
specific points.

## The algorithm

Given a query and a token budget, assemble a structured context in
three phases with a fixed 60/30/10 split:

  Phase 1 — Own-stage (60% of budget)
    Search the current stage's memories by query.
    Select chunks via submodular coverage (Krause & Guestrin 2008)
    instead of top-k, to avoid near-duplicate drowning.

  Phase 2 — Adjacent stages via entity graph (30% of budget)
    Extract entities from Phase 1 results.
    Run Personalized PageRank (HippoRAG, Gutiérrez NeurIPS 2024) over
    Cortex's entity graph seeded on those entities.
    Select cross-stage memories ranked by PPR mass.

  Phase 3 — Summary fallback (10% of budget)
    For stages not covered by Phase 1+2, retrieve pre-computed
    schema-structured summaries ordered by stage proximity.

## Output

A `StageContextResult` with four fields:
  - own_stage_context: Phase 1 text
  - adjacent_stage_context: Phase 2 text
  - stage_summaries: Phase 3 text
  - assembled_context: all three concatenated with section headers,
    ready to be fed into `decomposer.assemble_prompt` as a single
    placeholder or split into multiple placeholders by priority.

## What's the user's design vs what's paper-backed

  - The 3-phase structure, the 60/30/10 split, and the section labels
    are Clément Deust's invention (Swift original).
  - Phase 1 candidate SOURCE (dense WRRF over the stage's memories) is
    Cortex's existing primitive.
  - Phase 1 SELECTION (submodular coverage) is Krause & Guestrin 2008.
  - Phase 2 GRAPH SOURCE (Cortex's entity + relationship tables) is
    Cortex's existing primitive.
  - Phase 2 WALK (Personalized PageRank) is HippoRAG NeurIPS 2024.
  - Phase 3 SUMMARIES (schema-structured) uses Cortex's
    `schema_engine.py` (Tse 2007 schema-congruent consolidation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from mcp_server.core.context_assembly.coverage import submodular_select
from mcp_server.core.context_assembly.ppr_traversal import (
    build_entity_adjacency,
    personalized_pagerank,
    score_memories_by_ppr,
)
from mcp_server.core.context_assembly.stage_detector import StageDetector
from mcp_server.core.context_assembly.stage_phases import (
    phase_budget,
    render_adjacent,
    render_own_stage,
    render_summaries,
)


# ── Budget split ────────────────────────────────────────────────────────

# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_SPLIT_SUM_TOLERANCE = 1e-3


@dataclass(frozen=True)
class BudgetSplit:
    """Three-phase budget proportions. Must sum to 1.0."""

    own_stage: float = 0.6
    adjacent: float = 0.3
    summaries: float = 0.1

    def __post_init__(self) -> None:
        total = self.own_stage + self.adjacent + self.summaries
        if abs(total - 1.0) > _SPLIT_SUM_TOLERANCE:
            raise ValueError(f"BudgetSplit must sum to 1.0, got {total}")


DEFAULT_SPLIT = BudgetSplit()


# ── Result container ────────────────────────────────────────────────────


@dataclass
class StageContextResult:
    """Structured output of the 3-phase assembler.

    ``selected_memories`` contains the actual memory dicts that were
    chosen in Phase 1 and Phase 2, each tagged with a ``phase`` field
    (1 or 2). This is what downstream evaluators read when computing
    retrieval hits — the concatenated text fields are for the LLM
    reader, not for scoring.
    """

    own_stage_context: str = ""
    adjacent_stage_context: str = ""
    stage_summaries: str = ""
    assembled_context: str = ""
    selected_memories: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Port: resource types ────────────────────────────────────────────────


@dataclass
class StageCandidate:
    """A memory candidate annotated with its stage membership."""

    memory: dict[str, Any]
    stage_id: str
    score: float


# ── Main assembler ──────────────────────────────────────────────────────


class StageAwareContextAssembler:
    """Three-phase context assembler for stage-scoped retrieval.

    Wire dependencies at construction time. All external calls are
    callbacks so this module stays dependency-free (no direct pg_store,
    no direct embeddings, no direct schema_engine).

    Args:
        stage_detector: strategy for mapping memories to stages.
        retrieve_fn: callback that searches for candidates given
            (query, stage_id, max_results). Returns list of memory dicts
            with at least content, memory_id, score. For Phase 1.
        entity_graph_fn: callback that returns
            (entities, relationships) for the corpus. For Phase 2.
        memories_by_entity_fn: callback mapping entity_id → list of
            memories containing that entity. For Phase 2 aggregation.
        stage_summary_fn: callback that returns a schema-structured
            summary string for a given stage_id. For Phase 3.
    """

    def __init__(
        self,
        *,
        stage_detector: StageDetector,
        retrieve_fn: Callable[[str, str, int], list[dict[str, Any]]],
        entity_graph_fn: Callable[
            [],
            tuple[list[dict[str, Any]], list[dict[str, Any]]],
        ],
        memories_by_entity_fn: Callable[[list[str]], list[dict[str, Any]]],
        stage_summary_fn: Callable[[str], str],
    ) -> None:
        self._detector = stage_detector
        self._retrieve = retrieve_fn
        self._graph = entity_graph_fn
        self._mem_by_ent = memories_by_entity_fn
        self._summary = stage_summary_fn

    def assemble(
        self,
        *,
        query: str,
        current_stage: str,
        token_budget: int | None = None,
        budget_split: BudgetSplit = DEFAULT_SPLIT,
        max_chunks_per_phase: int = 5,
        diversity_lambda: float = 0.5,
    ) -> StageContextResult:
        """Run the 3-phase assembly.

        When ``token_budget`` is ``None``, the assembler selects purely
        by ``max_chunks_per_phase`` without token truncation — used for
        retrieval evaluation where text length is irrelevant and the
        metric is rank-based. When a reader is downstream, the caller
        should pass ``reasoner.context_window * 0.75`` to enforce a
        real budget (the Swift ContextDecomposer pattern).

        Under a budget every selected item still reaches the output: a
        phase condenses over-share items (``stage_phases``) rather than
        dropping them, so the selected-memory count never depends on
        how long the individual memories happen to be.
        """
        selected_own = self._select_own_stage(
            query, current_stage, max_chunks_per_phase, diversity_lambda
        )
        own_text, own_tokens, own_records = render_own_stage(
            selected_own, phase_budget(token_budget, budget_split.own_stage)
        )
        adjacent_text, adjacent_tokens, adj_records, covered_stages = self._adjacent(
            selected_own,
            current_stage,
            phase_budget(token_budget, budget_split.adjacent),
            max_chunks_per_phase,
        )
        summary_text, summary_tokens, summary_stages = self._summaries(
            covered_stages, phase_budget(token_budget, budget_split.summaries)
        )
        return StageContextResult(
            own_stage_context=own_text,
            adjacent_stage_context=adjacent_text,
            stage_summaries=summary_text,
            assembled_context=_join_sections(
                current_stage, own_text, adjacent_text, summary_text
            ),
            selected_memories=own_records + adj_records,
            metadata={
                "own_stage_chunks": len(selected_own),
                "own_stage_tokens": own_tokens,
                "adjacent_stages": sorted(covered_stages - {current_stage}),
                "adjacent_tokens": adjacent_tokens,
                "summary_stages": summary_stages,
                "summary_tokens": summary_tokens,
                "total_tokens": own_tokens + adjacent_tokens + summary_tokens,
                "token_budget": token_budget,
                "budget_split": (
                    budget_split.own_stage,
                    budget_split.adjacent,
                    budget_split.summaries,
                ),
            },
        )

    # ── Phase 1 ───────────────────────────────────────────────────────

    def _select_own_stage(
        self,
        query: str,
        current_stage: str,
        max_chunks_per_phase: int,
        diversity_lambda: float,
    ) -> list[dict[str, Any]]:
        """Select the own-stage chunks. Selection ignores the budget.

        Ranking metrics must not depend on memory length, so selection
        picks up to ``max_chunks_per_phase`` items and leaves the budget
        to text assembly, which condenses instead of dropping.
        """
        candidates = self._retrieve(query, current_stage, max_chunks_per_phase * 3)
        return submodular_select(
            candidates,
            token_budget=None,
            diversity_lambda=diversity_lambda,
            max_chunks=max_chunks_per_phase,
        )

    # ── Phase 2 ───────────────────────────────────────────────────────

    def _adjacent(
        self,
        selected_own: list[dict[str, Any]],
        current_stage: str,
        budget: int | None,
        max_chunks_per_phase: int,
    ) -> tuple[str, int, list[dict[str, Any]], set[str]]:
        """Cross-stage context reached by PPR from Phase 1's entities."""
        seed_entities: dict[str, float] = {}
        for chunk in selected_own:
            for entity_id in chunk.get("entity_ids", []) or []:
                key = str(entity_id)
                seed_entities[key] = seed_entities.get(key, 0.0) + 1.0
        if not seed_entities:
            return "", 0, [], {current_stage}

        entities, relationships = self._graph()
        ppr = personalized_pagerank(
            build_entity_adjacency(entities, relationships), seed_entities
        )
        top_entity_ids = sorted(ppr.keys(), key=lambda k: ppr[k], reverse=True)[:50]
        cross_stage = [
            m
            for m in self._mem_by_ent(top_entity_ids)
            if self._detector.stage_of(m) != current_stage
        ]
        scored = score_memories_by_ppr(cross_stage, ppr)
        text, used, records = render_adjacent(scored, budget, max_chunks_per_phase)
        covered = {current_stage} | {
            self._detector.stage_of(m) for m, _ in scored[:max_chunks_per_phase]
        }
        return text, used, records, covered

    # ── Phase 3 ───────────────────────────────────────────────────────

    def _summaries(
        self, covered_stages: set[str], budget: int | None
    ) -> tuple[str, int, list[str]]:
        """Schema summaries for the stages Phases 1-2 did not cover."""
        all_stages = self._detector.all_stages([])  # detectors may cache
        pairs = []
        for stage_id in all_stages:
            if stage_id in covered_stages:
                continue
            summary = self._summary(stage_id)
            if summary:
                pairs.append((stage_id, summary))
        return render_summaries(pairs, budget)


def _join_sections(
    current_stage: str, own_text: str, adjacent_text: str, summary_text: str
) -> str:
    """Concatenate the non-empty phase texts under their section headers."""
    sections = [
        (own_text, f"## Current Stage Context ({current_stage})"),
        (adjacent_text, "## Related Prior Context"),
        (summary_text, "## Stage Summaries"),
    ]
    return "\n\n".join(f"{header}\n\n{text}" for text, header in sections if text)
