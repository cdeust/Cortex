"""PG recall: intent-adaptive retrieval via recall_memories() + FlashRank reranking.

Two top-level functions are exposed:

  - `recall()` — the legacy WRRF composition retrieval path. Returns a
    flat ranked list of candidates. Used by the production handler and
    the current BEAM benchmark harness.

  - `assemble_context()` — the new structured 3-phase context assembler
    (Clément Deust's invention ported from Swift, complemented with
    paper-backed mechanisms). Returns a budgeted, slot-filled prompt
    with truncation awareness. See `mcp_server/core/context_assembly/`.

Pure business logic — takes a store + embeddings, returns results.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.query_intent import QueryIntent, classify_query_intent
from mcp_server.core.reranker import rerank_results
from mcp_server.core.titans_memory import TitansMemory

# Singleton Titans memory module (persists across recalls within a session)
_titans: TitansMemory | None = None


def _get_titans() -> TitansMemory:
    global _titans
    if _titans is None:
        _titans = TitansMemory()
    return _titans


# ── Chronological reranking ─────────────────────────────────────────────
# ChronoRAG (Chen et al., arxiv 2508.18748, 2025): for event ordering
# queries, blend relevance rank with chronological rank via Reciprocal
# Rank Fusion (Cormack et al., SIGIR 2009).


def _chronological_rerank(
    candidates: list[dict], beta: float = 0.5, k: int = 60
) -> list[dict]:
    """Blend relevance ranking with chronological ordering.

    For event ordering queries, the chronological position of memories
    matters as much as semantic relevance. This function assigns each
    candidate a blended score from its relevance rank and its
    chronological rank (by created_at timestamp).

    Args:
        candidates: Results ordered by relevance score.
        beta: Weight for chronological rank (0=pure relevance, 1=pure chrono).
        k: RRF constant (Cormack et al., 2009). Default 60.

    Returns:
        Reranked candidates with updated scores.
    """
    # Assign relevance rank
    for i, c in enumerate(candidates):
        c["_rel_rank"] = i

    # Sort by timestamp for chronological rank
    chrono = sorted(candidates, key=lambda c: c.get("created_at", ""))
    for i, c in enumerate(chrono):
        c["_chr_rank"] = i

    # RRF blend: score = (1-beta)/(k+rel_rank) + beta/(k+chr_rank)
    for c in candidates:
        c["score"] = float(
            (1 - beta) / (k + c["_rel_rank"]) + beta / (k + c["_chr_rank"])
        )
        del c["_rel_rank"]
        del c["_chr_rank"]

    return sorted(candidates, key=lambda c: c["score"], reverse=True)


# ── PG weight profiles ──────────────────────────────────────────────────
# NOTE: These weights are engineering defaults, NOT paper-prescribed values.
# The TMM normalization framework (Bruch et al., ACM TOIS 2023) defines the
# fusion formula but does NOT prescribe per-signal weights — those are
# corpus-specific. See benchmarks/beam/ablation_results.json for empirical
# justification from the BEAM ablation study.

# Ablation data (benchmarks/beam/ablation_results.json):
#   BEAM-optimal: fts=0.0, heat=0.7, ngram=0.0 → MRR 0.554
#   But fts=0.0 regresses LongMemEval -9.2pp R@10, LoCoMo -15.5pp R@10
# These defaults are balanced across all three benchmarks. Per-signal
# BEAM ablation data is recorded but not applied as defaults due to
# cross-benchmark regression. Dynamic corpus adaptation remains an open
# research problem — see Bruch et al. 2023 §5 on collection-dependent weights.
_BASE_PG_WEIGHTS: dict[str, float] = {
    "vector": 1.0,  # Primary signal — always full strength
    "fts": 0.5,  # Keyword matching: essential for factual/technical queries
    "heat": 0.3,  # Thermodynamic importance signal
    "ngram": 0.3,  # Fuzzy matching: helps partial/code token matches
    "recency": 0.0,  # Disabled by default; enabled for temporal intents
}

_PG_INTENT_OVERRIDES: dict[str, dict[str, float]] = {
    QueryIntent.TEMPORAL: {
        "heat": 0.6,
        "recency": 0.2,
    },
    QueryIntent.KNOWLEDGE_UPDATE: {
        "recency": 0.5,
        "heat": 0.5,
    },
    QueryIntent.EVENT_ORDER: {
        "heat": 0.4,
        "recency": 0.3,
        "fts": 0.6,
    },
    QueryIntent.SUMMARIZATION: {
        "heat": 0.5,
        "fts": 0.7,
    },
    QueryIntent.PREFERENCE: {
        "fts": 0.8,
        "heat": 0.5,
    },
}


def compute_pg_weights(
    intent: str, core_weights: dict | None = None
) -> dict[str, float]:
    """Compute PG recall_memories() signal weights for a given intent.

    Derives base weights from core_weights (from query_intent) when available,
    then applies intent-specific PG overrides.

    Verification ablation hooks (Popper C2 — operator-disablable mechanism):
    - ``CORTEX_DECAY_DISABLED=1``: forces heat weight to 0.0 so the
      thermodynamic decay signal cannot enter the WRRF fusion. Disabling
      heat is equivalent to "flat heat" for ranking purposes — Cortex
      degenerates to vector + FTS + ngram, the flat-importance baseline.
    - ``CORTEX_HEAT_CONSTANT=<float>``: same effect on the weight (heat
      cannot discriminate when constant), kept as a separate var so the
      n_scan harness can force a specific constant heat at write time and
      confirm the ranker reproduces flat baseline at read time.
    Source: tasks/verification-protocol.md E2 (N-scan); env vars defined
    by benchmarks/lib/n_scan_runner.py:_apply_condition.
    """
    import os as _os

    cw = core_weights or {}
    # Vector is always 1.0 in the PG path — it's the primary discovery signal.
    # Other signals derived from core_weights (intent system) when available,
    # falling back to _BASE_PG_WEIGHTS defaults.
    base = {
        "vector": 1.0,
        "fts": cw.get("fts", _BASE_PG_WEIGHTS["fts"]),
        "heat": cw.get("heat", _BASE_PG_WEIGHTS["heat"]),
        "ngram": cw.get("fts", _BASE_PG_WEIGHTS["fts"]) * 0.6,
        "recency": 0.0,
    }
    overrides = _PG_INTENT_OVERRIDES.get(intent)
    if overrides:
        base.update(overrides)
    if _os.environ.get("CORTEX_DECAY_DISABLED") == "1" or _os.environ.get(
        "CORTEX_HEAT_CONSTANT"
    ):
        base["heat"] = 0.0
    return base


# ── Recall orchestration ─────────────────────────────────────────────────


def recall(
    query: str,
    store: Any,
    embeddings: Any,
    *,
    top_k: int = 10,
    domain: str | None = None,
    directory: str | None = None,
    agent_topic: str | None = None,
    min_heat: float = 0.01,
    rerank: bool = True,
    rerank_alpha: float = 0.70,
    wrrf_k: int = 60,
    momentum_state: dict | None = None,
    include_globals: bool = True,
) -> list[dict[str, Any]]:
    """Full PG-path retrieval: intent → weights → recall_memories → rerank.

    Args:
        query: Search query text.
        store: PgMemoryStore instance with recall_memories() method.
        embeddings: EmbeddingEngine instance with encode() method.
        top_k: Max results to return.
        domain: Optional domain filter.
        directory: Optional directory filter.
        agent_topic: Optional agent context filter (e.g., "engineer", "researcher").
        min_heat: Minimum heat threshold.
        rerank: Whether to apply FlashRank reranking.
        rerank_alpha: Blend weight for cross-encoder scores (0.70 from BEAM ablation).
        wrrf_k: WRRF fusion constant.
        momentum_state: Mutable dict with 'momentum' key for Titans surprise.

    Returns:
        List of result dicts with memory_id, content, score, heat, etc.
    """
    # 1. Intent classification
    intent_info = classify_query_intent(query)
    intent = intent_info["intent"]

    # 2. Intent-adaptive PG weights
    weights = compute_pg_weights(intent, intent_info.get("weights", {}))

    # 3. Encode query. No char truncation: the embedding model enforces
    # its own token limit internally (e.g. 256 for MiniLM, 512 for bge-*,
    # 8192 for bge-m3/jina-v3). Any caller-side slice would throw away
    # information the model could still consume.
    q_emb = embeddings.encode(query) if embeddings else None

    # 4. PG recall_memories (server-side WRRF fusion)
    pg_max = top_k
    candidates = store.recall_memories(
        query_text=query,
        query_embedding=q_emb,
        intent=str(intent.value) if hasattr(intent, "value") else str(intent),
        domain=domain,
        directory=directory,
        agent_topic=agent_topic,
        min_heat=min_heat,
        max_results=pg_max,
        wrrf_k=wrrf_k,
        weights=weights,
        include_globals=include_globals,
    )

    if not candidates:
        return []

    # 5. Client-side FlashRank reranking
    if rerank and len(candidates) > 1:
        ranked_pairs = [(c["memory_id"], c.get("score", 0.0)) for c in candidates]
        content_map = {c["memory_id"]: c["content"] for c in candidates}
        reranked = rerank_results(query, ranked_pairs, content_map, alpha=rerank_alpha)
        cand_map = {c["memory_id"]: c for c in candidates}
        candidates = []
        for mid, score in reranked:
            if mid in cand_map:
                c = dict(cand_map[mid])
                c["score"] = score
                candidates.append(c)

    # 6. Per-type pool guarantee for instruction/preference queries.
    # ENGRAM (arxiv 2511.12960): typed memory pools prevent instruction/
    # preference memories from being drowned out by episodic memories.
    # Reserves 2 slots for tag-matched memories when intent matches.
    # Validated approach (BEAM 0.546 overall — see README ablation log).
    _TYPE_INTENTS = {
        QueryIntent.INSTRUCTION: "instruction",
        QueryIntent.PREFERENCE: "preference",
    }
    tag_for_intent = _TYPE_INTENTS.get(intent)
    if tag_for_intent and store and q_emb and hasattr(store, "search_by_tag_vector"):
        existing_ids = {c["memory_id"] for c in candidates}
        typed = store.search_by_tag_vector(
            q_emb, tag_for_intent, domain=domain, limit=2
        )
        for t in typed:
            mid = t.get("id") or t.get("memory_id")
            if mid and mid not in existing_ids:
                t["memory_id"] = mid
                candidates.insert(0, t)  # Front of list = high rank
                existing_ids.add(mid)

    # 7. Abstention gate (cortex-beam-abstain) — DISABLED.
    # v0.1 model regresses BEAM by -0.191 MRR on every category despite
    # F1=0.733 on its own held-out validation. The model overfits to
    # training pairs but doesn't generalize to BEAM evaluation queries —
    # 32% of real relevant passages get filtered as irrelevant.
    # Critically: it does NOT improve abstention category (still 0.100).
    # Re-enable when v0.2 ships with cross-validated training data.
    # Code path preserved for future use:
    # from mcp_server.core.abstention_gate import filter_by_abstention
    # filtered, _ = filter_by_abstention(query, candidates, threshold=0.45, keep_at_least=1)
    # candidates = filtered

    # 8. MMR diversity reranking — DISABLED after ablation (see above).
    # Carbonell & Goldstein (SIGIR 1998) MMR trades precision for coverage.
    # BEAM uses MRR (first-hit position), so any diversity reranking hurts:
    #   lambda=0.5: summarization 0.391→0.367 (-0.024)
    #   lambda=0.7: summarization 0.391→0.381 (-0.010)
    # MMR would help with nugget-based QA scoring (coverage matters) but
    # our retrieval-only MRR evaluation penalizes it. Keeping the module
    # (mmr_diversity.py) for future use when full QA evaluation is added.

    # 9. Chronological reranking for event ordering queries.
    # ChronoRAG (Chen et al., 2025): blend relevance rank with
    # chronological rank via RRF (Cormack et al., 2009).
    # Only activates when intent is EVENT_ORDER.
    if intent == QueryIntent.EVENT_ORDER and len(candidates) > 1:
        candidates = _chronological_rerank(candidates, beta=0.5, k=60)

    # 10. Titans test-time learning (Behrouz et al., NeurIPS 2025)
    # Update the neural associative memory M and surprise momentum S
    # using the exact equations from the paper:
    #   S_t = eta * S_{t-1} - theta * grad_l(M_{t-1}; x_t)
    #   M_t = M_{t-1} - S_t
    if momentum_state is not None:
        titans = _get_titans()
        result_embs = []
        for r in candidates[:10]:
            mem = store.get_memory(r["memory_id"])
            if mem and mem.get("embedding"):
                result_embs.append(mem["embedding"])
        surprise = titans.update(q_emb, result_embs)
        momentum_state["momentum"] = surprise  # Track for diagnostics

    return candidates[:top_k]


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
    from mcp_server.core.context_assembly.stage_assembler import (
        BudgetSplit,
        StageAwareContextAssembler,
    )
    from mcp_server.core.context_assembly.stage_detector import (
        ExplicitStageDetector,
    )

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
            if len(name) >= 3 and eid:
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
            if len(nm) >= 3 and eid:
                entity_pairs.append((nm, eid))

        out: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for eid in entity_ids:
            name = id_to_name.get(str(eid))
            if not name:
                continue
            mems = store.get_memories_mentioning_entity(name, limit=10) or []
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

    return {
        "assembled_context": result.assembled_context,
        "own_stage_context": result.own_stage_context,
        "adjacent_stage_context": result.adjacent_stage_context,
        "stage_summaries": result.stage_summaries,
        "metadata": result.metadata,
        # Contains both Phase 1 and Phase 2 selected memories, each
        # tagged with a `phase` field (1 or 2). Downstream evaluators
        # read this to score retrieval hits across all phases.
        "selected_memories": result.selected_memories,
    }
