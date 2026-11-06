"""Post-WRRF reranking/orchestration stages consumed by ``run_recall_pipeline``.

source: ADR-0220"""

from __future__ import annotations

from mcp_server.shared.telemetry_context import set_retrieval_tier
from mcp_server.shared.memory_rows import MemoryRows
from mcp_server.core.pg_recall_context import RecallContext, fetch_and_triage
from mcp_server.core.pg_recall_signals import (
    _get_active_goal,
    _get_titans,
    _get_user_mood,
)
from mcp_server.core.query_intent import QueryIntent
from mcp_server.core.reranker import rerank_results
from mcp_server.core.recall_pipeline import (
    attentional_focus_rerank,
    conflict_monitor_rerank,
    dendritic_modulate,
    emotional_retrieval_rerank,
    goal_maintenance_rerank,
    hdc_rerank,
    hopfield_complete,
    mood_congruent_rerank,
    reconsolidation_apply,
    spreading_activation_expand,
    spreading_activation_tail_fill,
    value_priority_rerank,
)


def _chronological_rerank(
    candidates: list[dict], beta: float = 0.5, k: int = 60
) -> list[dict]:
    """Blend relevance ranking with chronological ordering.

    source: ADR-0220

    Args:
        candidates: Results ordered by relevance score.
        beta: Chronological weight (0=pure relevance, 1=pure chronology).
        k: RRF constant (default 60).
    source: ADR-0220

    Returns:
        Reranked candidates with updated scores.
    """
    for i, c in enumerate(candidates):
        c["_rel_rank"] = i

    chrono = sorted(candidates, key=lambda c: c.get("created_at", ""))
    for i, c in enumerate(chrono):
        c["_chr_rank"] = i

    for c in candidates:
        c["score"] = float(
            (1 - beta) / (k + c["_rel_rank"]) + beta / (k + c["_chr_rank"])
        )
        del c["_rel_rank"]
        del c["_chr_rank"]

    return sorted(candidates, key=lambda c: c["score"], reverse=True)


def apply_recollection_pipeline(
    candidates: list[dict], ctx: RecallContext
) -> list[dict]:
    """Apply post-WRRF recollection stages 4a through 4g.

    source: ADR-0220
    """
    candidates = hopfield_complete(
        candidates,
        ctx.q_emb,
        ctx.candidate_embeddings if ctx.candidate_embeddings is not None else ctx.store,
        embedding_dim=ctx.embeddings.dimensions if ctx.embeddings else 0,
    )
    candidates = hdc_rerank(candidates, ctx.query)
    if ctx.sa_mode == "augment":
        candidates = spreading_activation_expand(
            candidates,
            ctx.query,
            ctx.store,
            domain=ctx.domain,
            include_globals=ctx.include_globals,
            cross_domain=ctx.cross_domain,
        )
    candidates = dendritic_modulate(candidates, ctx.query, ctx.store)
    candidates = emotional_retrieval_rerank(candidates, ctx.query)
    candidates = mood_congruent_rerank(candidates, _get_user_mood(ctx.store))
    return reconsolidation_apply(candidates, query=ctx.query, store=ctx.store)


def apply_rerank_nudges(candidates: list[dict], ctx: RecallContext) -> list[dict]:
    """FlashRank cross-encoder rerank + the post-rerank multiplicative nudges.

    source: ADR-0220"""
    if ctx.rerank and len(candidates) > 1:
        ranked_pairs = [(c["memory_id"], c.get("score", 0.0)) for c in candidates]
        content_map = {c["memory_id"]: c["content"] for c in candidates}
        reranked = rerank_results(
            ctx.query, ranked_pairs, content_map, alpha=ctx.rerank_alpha
        )
        cand_map = {c["memory_id"]: c for c in candidates}
        candidates = []
        for mid, score in reranked:
            if mid in cand_map:
                c = dict(cand_map[mid])
                c["score"] = score
                candidates.append(c)

    candidates = value_priority_rerank(candidates)
    candidates = conflict_monitor_rerank(candidates, ctx.store)
    candidates = goal_maintenance_rerank(candidates, _get_active_goal(ctx.store))
    return attentional_focus_rerank(candidates, ctx.query)


# source: ADR-0220


_TYPE_INTENTS = {
    QueryIntent.INSTRUCTION: "instruction",
    QueryIntent.PREFERENCE: "preference",
}


def reserve_typed_pool(candidates: list[dict], ctx: RecallContext) -> list[dict]:
    """Reserve up to 2 tag-matched slots at the front for typed intents."""
    tag_for_intent = _TYPE_INTENTS.get(ctx.intent)
    if not (
        tag_for_intent
        and ctx.store
        and ctx.q_emb
        and hasattr(ctx.store, "search_by_tag_vector")
    ):
        return candidates
    existing_ids = {c["memory_id"] for c in candidates}
    typed = ctx.store.search_by_tag_vector(
        ctx.q_emb, tag_for_intent, domain=ctx.domain, limit=2
    )
    for t in typed:
        mid = t.get("id") or t.get("memory_id")
        if mid and mid not in existing_ids:
            t["memory_id"] = mid
            candidates.insert(0, t)  # Front of list = high rank
            existing_ids.add(mid)
    return candidates


# source: ADR-0220


def apply_final_stages(candidates: list[dict], ctx: RecallContext) -> list[dict]:
    """Event-order rerank, Titans test-time update, tail-mode SA fill.

    source: ADR-0220"""
    if ctx.intent == QueryIntent.EVENT_ORDER and len(candidates) > 1:
        candidates = _chronological_rerank(candidates, beta=0.5, k=60)

    if ctx.momentum_state is not None:
        titans = _get_titans()
        ids = [r["memory_id"] for r in candidates[:10]]
        # Match get_memory rows on both backends: SQLite rows have no embedding.
        memories = MemoryRows.read(ctx.store, ids)
        result_embs = []
        for memory_id in ids:
            emb = (memories.get_memory(memory_id) or {}).get("embedding")
            if emb is not None and len(emb):
                result_embs.append(emb)
        surprise = titans.update(ctx.q_emb, result_embs)
        ctx.momentum_state["momentum"] = surprise  # Track for diagnostics

    if ctx.sa_mode == "tail":
        candidates = spreading_activation_tail_fill(
            candidates,
            ctx.query,
            ctx.store,
            ctx.top_k,
            domain=ctx.domain,
            include_globals=ctx.include_globals,
            cross_domain=ctx.cross_domain,
        )
    return candidates


def run_recall_pipeline(ctx: RecallContext) -> list[dict]:
    """The full ``recall()`` implementation: fetch, triage, run every
    post-WRRF stage in order, return the top_k slice.

    source: ADR-0220"""
    set_retrieval_tier("pg")
    top_k = ctx.top_k
    candidates, ctx, early_return = fetch_and_triage(ctx)
    if early_return:
        return candidates[:top_k]

    candidates = apply_recollection_pipeline(candidates, ctx)
    candidates = apply_rerank_nudges(candidates, ctx)
    candidates = reserve_typed_pool(candidates, ctx)
    candidates = apply_final_stages(candidates, ctx)
    return candidates[:top_k]
