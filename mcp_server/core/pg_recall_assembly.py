"""Structured 3-phase context assembly (issue #368 split).

Extracted verbatim from ``core/pg_recall.py``, which had grown to 833 lines
against the 500-line limit in coding-standards.md §4.1. The seam is the one
the file already documented with its own section banner: recall ORCHESTRATION
(intent, weights, WRRF, reranking) on one side, and the budgeted slot-filled
CONTEXT ASSEMBLY that consumes recall's output on the other. They change for
different reasons — the first when ranking changes, the second when the
prompt budget or stage model changes — so §1.1 puts them in different files.

``pg_recall`` re-exports ``assemble_context`` so no caller had to move; that
facade holds no implementation (same pattern as ``synaptic_plasticity.py``).
"""

from __future__ import annotations
from typing import Any

from mcp_server.core.context_assembly.condensers import condense_assembled_context
from mcp_server.core.context_assembly.stage_assembler import (
    BudgetSplit,
    StageAwareContextAssembler,
)
from mcp_server.core.context_assembly.stage_detector import ExplicitStageDetector

# Entity names shorter than this are too generic to match against content.
# source: pre-existing tuned value, moved unchanged with its only consumer in
# the #368 split (was #197 family 3); provenance not recorded at introduction.
_MIN_ENTITY_NAME_LEN = 3


# ── Structured 3-phase context assembly (new path) ─────────────────────


def assemble_context(
    query: str,
    store: Any,
    embeddings: Any,
    *,
    current_stage: str,
    token_budget: int | None = None,
    domain: str | None = None,
    stage_field: str = "plan_id",
    budget_split: tuple[float, float, float] = (0.6, 0.3, 0.1),
    max_chunks_per_phase: int = 5,
    diversity_lambda: float = 0.0,
    stage_detector: Any | None = None,
) -> dict[str, Any]:
    """Structured 3-phase context assembly for a single query.

    Returns a `dict` with:
      - 'assembled_context' (str): the full prompt-ready text
      - 'own_stage_context' (str), 'adjacent_stage_context' (str),
        'stage_summaries' (str): the three phases separately
      - 'metadata' (dict): bookkeeping (token counts, stages covered)
      - 'selected_memories' (list[dict]): the memory dicts chosen in
        Phase 1 + Phase 2, with their 'memory_id' preserved so the
        caller can score retrieval hits against gold.

    This is the new retrieval primitive that replaces flat top-k for
    long-context scenarios. See `mcp_server/core/context_assembly/` for
    the full design and paper citations.

    Args:
        query: raw user query text.
        store: PgMemoryStore (for entity graph + memory fetch).
        embeddings: EmbeddingEngine (for query encoding in Phase 1).
        current_stage: the stage ID the query is "about" (e.g. the
            conversation ID for BEAM, or the current agent_topic for
            production).
        token_budget: target total tokens for the assembled context.
            Default 6000 matches Swift Stage5PRD.
        domain: optional domain filter for Phase 1 retrieval.
        stage_field: memory field used to determine stage. Default
            "plan_id" for BEAM; use "agent_topic" or similar in prod.
        budget_split: (own, adjacent, summaries) proportions summing
            to 1.0. Default (0.6, 0.3, 0.1) matches Swift.
        max_chunks_per_phase: hard cap on chunks selected per phase.
        diversity_lambda: MMR diversity weight for Phase 1 submodular
            selection. Default 0.5.
    """

    split = BudgetSplit(
        own_stage=budget_split[0],
        adjacent=budget_split[1],
        summaries=budget_split[2],
    )
    # Use the caller-provided detector if given, else default to Explicit
    if stage_detector is not None:
        detector = stage_detector
    else:
        detector = ExplicitStageDetector(field=stage_field)

    # Cache entity graph + entity-id→name lookup once per assemble call
    # so we don't re-query on every phase.
    _graph_cache: dict[str, Any] = {}

    def _ensure_graph() -> dict[str, Any]:
        if _graph_cache:
            return _graph_cache
        entities = (
            store.get_all_entities() if hasattr(store, "get_all_entities") else []
        )
        relationships = (
            store.get_all_relationships()
            if hasattr(store, "get_all_relationships")
            else []
        )
        _graph_cache["entities"] = entities
        _graph_cache["relationships"] = relationships
        _graph_cache["id_to_name"] = {
            str(e.get("id")): e.get("name", "") for e in entities
        }
        _graph_cache["name_to_id"] = {
            (e.get("name") or "").lower(): str(e.get("id")) for e in entities
        }
        return _graph_cache

    # ── Retrieval callback for Phase 1 (own-stage) ────────────────────
    # Runs intent-adaptive recall, filters to current stage, and tags
    # each candidate with its entity IDs. Entity lookup uses substring
    # matching of known entity names against memory content — NOT a
    # fresh extraction pass. The reason: knowledge_graph.extract_entities
    # is regex-based for code patterns (imports, def, class) and misses
    # all entities from prose content. But the graph WAS populated at
    # ingest time from the union of all memory contents, so every entity
    # appearing in any memory is present in the graph. Substring
    # matching from the graph down to each memory gives complete
    # memory→entity linkage for both code and prose.
    def _retrieve_fn(q: str, stage_id: str, max_results: int) -> list[dict[str, Any]]:
        # Deferred: assembly consumes recall's output, and pg_recall re-exports
        # assemble_context, so a module-level import here would close the cycle.
        # The dependency is genuinely one-directional at RUNTIME — assembly
        # calls recall, never the reverse — so the deferral expresses the real
        # shape rather than hiding a design problem.
        from mcp_server.core.pg_recall import recall  # noqa: PLC0415 — breaks the facade import cycle; see comment above

        candidates = recall(
            query=q,
            store=store,
            embeddings=embeddings,
            top_k=max_results * 3,
            domain=domain,
            include_globals=False,
            rerank=True,
        )
        graph = _ensure_graph()
        # Pre-compute (name_lower, eid) pairs once per Phase 1 call
        entity_pairs: list[tuple[str, str]] = []
        for e in graph.get("entities", []):
            name = (e.get("name") or "").strip().lower()
            eid = str(e.get("id", ""))
            if len(name) >= _MIN_ENTITY_NAME_LEN and eid:
                entity_pairs.append((name, eid))

        filtered: list[dict[str, Any]] = []
        for c in candidates:
            mem = store.get_memory(c["memory_id"])
            if not mem:
                continue
            if detector.stage_of(mem) != stage_id:
                continue
            content_lower = (mem.get("content") or "").lower()
            entity_ids_for_mem: list[str] = [
                eid for name, eid in entity_pairs if name in content_lower
            ]
            c_out = dict(c)
            c_out["embedding"] = mem.get("embedding")
            c_out["entity_ids"] = entity_ids_for_mem
            filtered.append(c_out)
            if len(filtered) >= max_results:
                break
        return filtered

    # ── Entity graph callback for Phase 2 ─────────────────────────────
    def _entity_graph_fn() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        graph = _ensure_graph()
        return graph["entities"], graph["relationships"]

    # ── Memories-by-entity callback for Phase 2 aggregation ───────────
    # Cortex's store looks up memories by entity NAME via FTS on content
    # (there is no junction table). We translate PPR top-k entity IDs
    # back to names and run a content search per name. Each returned
    # memory is annotated with its full entity_ids list (derived via
    # substring match against the graph) so score_memories_by_ppr can
    # compute PPR mass correctly — without this, mass is always 0 and
    # Phase 2 returns nothing.
    def _memories_by_entity_fn(
        entity_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not hasattr(store, "get_memories_mentioning_entity"):
            return []
        graph = _ensure_graph()
        id_to_name: dict[str, str] = graph["id_to_name"]
        # Build (name_lower, eid) pairs once for entity_ids enrichment
        entity_pairs: list[tuple[str, str]] = []
        for e in graph.get("entities", []):
            nm = (e.get("name") or "").strip().lower()
            eid = str(e.get("id", ""))
            if len(nm) >= _MIN_ENTITY_NAME_LEN and eid:
                entity_pairs.append((nm, eid))

        out: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for eid in entity_ids:
            name = id_to_name.get(str(eid))
            if not name:
                continue
            # heads_only: Phase 2 serves memory content into the assembled
            # context — supersession chain heads only.
            mems = (
                store.get_memories_mentioning_entity(name, limit=10, heads_only=True)
                or []
            )
            for m in mems:
                mid = m.get("id") or m.get("memory_id")
                if mid is None or mid in seen_ids:
                    continue
                if domain and m.get("domain") != domain:
                    continue
                seen_ids.add(mid)
                content_lower = (m.get("content") or "").lower()
                m_entity_ids = [
                    pid for pname, pid in entity_pairs if pname in content_lower
                ]
                m_out = dict(m)
                m_out["memory_id"] = mid
                m_out["entity_ids"] = m_entity_ids
                out.append(m_out)
        return out

    # ── Stage summary callback for Phase 3 ────────────────────────────
    # For BEAM we don't have pre-computed summaries yet. Return the
    # first ~300 chars of the first memory in the stage as a proxy.
    # Production Cortex will wire this to dual_store_cls.py / schema_engine.
    def _stage_summary_fn(stage_id: str) -> str:
        # Minimal implementation: walk memories and return truncated
        # content of the first non-current-stage hit. Good enough for
        # the benchmark until we add real summarization.
        return ""

    assembler = StageAwareContextAssembler(
        stage_detector=detector,
        retrieve_fn=_retrieve_fn,
        entity_graph_fn=_entity_graph_fn,
        memories_by_entity_fn=_memories_by_entity_fn,
        stage_summary_fn=_stage_summary_fn,
    )

    result = assembler.assemble(
        query=query,
        current_stage=current_stage,
        token_budget=token_budget,
        budget_split=split,
        max_chunks_per_phase=max_chunks_per_phase,
        diversity_lambda=diversity_lambda,
    )

    # Truncation-awareness pass: each phase above enforces its own
    # sub-budget independently (per-phase submodular selection caps),
    # so their sum can still exceed the caller's total token_budget —
    # estimate_tokens is a heuristic and per-phase caps do not
    # renegotiate against each other. condense_assembled_context is a
    # no-op (returns the identical header+concatenation) whenever the
    # three phases already fit; only priority-condenses when they don't.
    # Skipped when token_budget is None (stage_assembler's own
    # "no token truncation" mode — nothing to condense against).
    assembled_context = result.assembled_context
    if token_budget is not None:
        assembled_context = condense_assembled_context(
            result.own_stage_context,
            result.adjacent_stage_context,
            result.stage_summaries,
            current_stage,
            token_budget,
        )

    return {
        "assembled_context": assembled_context,
        "own_stage_context": result.own_stage_context,
        "adjacent_stage_context": result.adjacent_stage_context,
        "stage_summaries": result.stage_summaries,
        "metadata": result.metadata,
        # Contains both Phase 1 and Phase 2 selected memories, each
        # tagged with a `phase` field (1 or 2). Downstream evaluators
        # read this to score retrieval hits across all phases.
        "selected_memories": result.selected_memories,
    }
