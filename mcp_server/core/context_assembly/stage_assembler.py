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

from mcp_server.core.context_assembly.budget import estimate_tokens
from mcp_server.core.context_assembly.coverage import submodular_select
from mcp_server.core.context_assembly.ppr_traversal import (
    build_entity_adjacency,
    personalized_pagerank,
    score_memories_by_ppr,
)
from mcp_server.core.context_assembly.stage_detector import StageDetector


# ── Budget split ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetSplit:
    """Three-phase budget proportions. Must sum to 1.0."""

    own_stage: float = 0.6
    adjacent: float = 0.3
    summaries: float = 0.1

    def __post_init__(self) -> None:
        total = self.own_stage + self.adjacent + self.summaries
        if abs(total - 1.0) > 1e-3:
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
        """
        if token_budget is None:
            own_budget = None
            adj_budget = None
            sum_budget = None
        else:
            own_budget = int(token_budget * budget_split.own_stage)
            adj_budget = int(token_budget * budget_split.adjacent)
            sum_budget = int(token_budget * budget_split.summaries)

        # Track every memory we actually commit to the output so the
        # caller can score retrieval hits on the full selected set,
        # not just the text.
        selected_memories: list[dict[str, Any]] = []

        # ── Phase 1 — Own-stage ───────────────────────────────────────
        # Selection is decoupled from token budget: we always pick up
        # to max_chunks_per_phase items so retrieval ranking metrics
        # stay well-defined regardless of individual memory size. The
        # token budget is enforced at text-assembly time (below),
        # which may truncate individual chunks but never reduces the
        # count of selected items.
        own_chunks = self._retrieve(query, current_stage, max_chunks_per_phase * 3)
        selected_own = submodular_select(
            own_chunks,
            token_budget=None,
            diversity_lambda=diversity_lambda,
            max_chunks=max_chunks_per_phase,
        )
        for c in selected_own:
            selected_memories.append(
                {
                    "memory_id": c.get("memory_id"),
                    "content": c.get("content", ""),
                    "score": c.get("score", 0.0),
                    "phase": 1,
                }
            )
        own_text = "\n\n".join(c.get("content", "") for c in selected_own).strip()
        own_tokens = estimate_tokens(own_text)

        # ── Phase 2 — Adjacent stages via PPR ─────────────────────────
        # Extract entities from Phase 1 results
        seed_entities: dict[str, float] = {}
        for c in selected_own:
            for eid in c.get("entity_ids", []) or []:
                seed_entities[str(eid)] = seed_entities.get(str(eid), 0.0) + 1.0

        adjacent_text = ""
        adjacent_tokens = 0
        covered_stages = {current_stage}

        if seed_entities:
            entities, relationships = self._graph()
            adjacency = build_entity_adjacency(entities, relationships)
            ppr = personalized_pagerank(adjacency, seed_entities)

            # Fetch candidate memories that contain PPR-hot entities
            top_entity_ids = sorted(ppr.keys(), key=lambda k: ppr[k], reverse=True)[:50]
            candidate_mems = self._mem_by_ent(top_entity_ids)

            # Filter to NOT-current-stage and score by PPR
            cross_stage = [
                m for m in candidate_mems if self._detector.stage_of(m) != current_stage
            ]
            scored = score_memories_by_ppr(cross_stage, ppr)

            # Greedy pack within adjacent_budget (or ignore budget if None)
            adjacent_parts: list[str] = []
            used = 0
            for m, score in scored[: max_chunks_per_phase * 2]:
                content = m.get("content", "")
                t = estimate_tokens(content)
                if adj_budget is not None and used + t > adj_budget:
                    continue
                adjacent_parts.append(content)
                selected_memories.append(
                    {
                        "memory_id": m.get("memory_id") or m.get("id"),
                        "content": content,
                        "score": float(score),
                        "phase": 2,
                    }
                )
                used += t
                covered_stages.add(self._detector.stage_of(m))
                if len(adjacent_parts) >= max_chunks_per_phase:
                    break
            adjacent_text = "\n\n".join(adjacent_parts).strip()
            adjacent_tokens = used

        # ── Phase 3 — Summary fallback ────────────────────────────────
        summary_parts: list[str] = []
        summary_tokens = 0
        all_stages = self._detector.all_stages([])  # detectors may cache
        uncovered_stages = [s for s in all_stages if s not in covered_stages]
        for stage_id in uncovered_stages:
            summary = self._summary(stage_id)
            if not summary:
                continue
            t = estimate_tokens(summary)
            if sum_budget is not None and summary_tokens + t > sum_budget:
                break
            summary_parts.append(f"[{stage_id}] {summary}")
            summary_tokens += t
        summary_text = "\n\n".join(summary_parts).strip()

        # ── Assemble ──────────────────────────────────────────────────
        parts: list[str] = []
        if own_text:
            parts.append(f"## Current Stage Context ({current_stage})\n\n{own_text}")
        if adjacent_text:
            parts.append(f"## Related Prior Context\n\n{adjacent_text}")
        if summary_text:
            parts.append(f"## Stage Summaries\n\n{summary_text}")
        assembled = "\n\n".join(parts)

        total_tokens = own_tokens + adjacent_tokens + summary_tokens

        return StageContextResult(
            own_stage_context=own_text,
            adjacent_stage_context=adjacent_text,
            stage_summaries=summary_text,
            assembled_context=assembled,
            selected_memories=selected_memories,
            metadata={
                "own_stage_chunks": len(selected_own),
                "own_stage_tokens": own_tokens,
                "adjacent_stages": sorted(covered_stages - {current_stage}),
                "adjacent_tokens": adjacent_tokens,
                "summary_stages": uncovered_stages[: len(summary_parts)],
                "summary_tokens": summary_tokens,
                "total_tokens": total_tokens,
                "token_budget": token_budget,
                "budget_split": (
                    budget_split.own_stage,
                    budget_split.adjacent,
                    budget_split.summaries,
                ),
            },
        )
