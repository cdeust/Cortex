"""Post-WRRF reranking/orchestration stages consumed by ``run_recall_pipeline``.

Split from pg_recall.py (continuing the two documented seams cut at #368 —
pg_recall_weights.py / pg_recall_assembly.py — with two more:
pg_recall_context.py and this file) to bring pg_recall.py under this
repo's local 300-line file cap and 40-line method cap (CLAUDE.md § Code
Style; a tightening of coding-standards.md §4.1/§4.2). Every value moved
unchanged — this re-homes code, it retunes nothing.

Every stage function takes exactly ``(candidates, ctx: RecallContext)`` —
see pg_recall_context.py for why the call-site invariants are bundled into
one object rather than passed as 8-13 positional parameters
(coding-standards.md §4.4, Introduce Parameter Object).
"""

from __future__ import annotations

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

    ChronoRAG (Chen et al., arxiv 2508.18748, 2025): for event ordering
    queries, chronological position matters as much as semantic relevance.
    Blends each candidate's relevance rank with its chronological rank via
    Reciprocal Rank Fusion (Cormack et al., SIGIR 2009).

    Args:
        candidates: Results ordered by relevance score.
        beta: Weight for chronological rank (0=pure relevance, 1=pure chrono).
        k: RRF constant (Cormack et al., 2009). Default 60.

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
    """Post-WRRF paper-mechanism recollection chain (stages 4a-4g).

    Each stage is gated by ``CORTEX_ABLATE_<MECH>=1`` (returns input
    unchanged when ablated). Order: HOPFIELD (Ramsauer 2021 attention),
    HDC (Kanerva 2009 bipolar algebra), SPREADING_ACTIVATION (Collins &
    Loftus 1975 BFS over the entity graph — AUGMENT mode only, may inject
    NEW candidates), DENDRITIC_CLUSTERS (Poirazi 2003 multiplicative
    modulation), EMOTIONAL_RETRIEVAL (Bower 1981 mood-congruent recall on
    the query's inferred valence), MOOD_CONGRUENT_RERANK (Bower 1981 on the
    user's session mood), RECONSOLIDATION (Nader, Schafe & LeDoux 2000,
    Nature 406(6797) — MUST be last so the mutation reflects the final
    ranking the user will see).
    """
    candidates = hopfield_complete(
        candidates,
        ctx.q_emb,
        ctx.store,
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

    FlashRank (client-side) reorders by content relevance. Then, in order:
    VALUE_PRIORITY (B2, weight 0.15, never overrides a strong content
    match), CONFLICT_MONITOR (A2 — Botvinick 2001; Miller & Cohen 2001 —
    demotes the losing memory of the most-contradictory pair),
    GOAL_MAINTENANCE (A3 — Miller & Cohen 2001, scales by goal relevance),
    ATTENTIONAL_CONTROL (A1 read-side — Baddeley 2003; Posner & Petersen
    1990; Cowan 2001, a soft re-weight over the full candidate set, not a
    truncation). Each stage no-ops (gain 1.0 / identity) absent its signal.
    """
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


# Per-type pool guarantee for instruction/preference queries. ENGRAM
# (arxiv 2511.12960): typed memory pools prevent instruction/preference
# memories from being drowned out by episodic memories. Reserves 2 slots
# for tag-matched memories when intent matches (validated — BEAM 0.546
# overall, see README ablation log).
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


# Abstention gate (cortex-beam-abstain) and MMR diversity reranking are both
# DISABLED after ablation — v0.1 abstention regresses BEAM by -0.191 MRR
# (see mcp_server/core/abstention_gate.py, ERA001/#239); MMR (Carbonell &
# Goldstein, SIGIR 1998) trades precision for coverage, which our MRR-based
# BEAM evaluation penalizes (lambda=0.5: summarization 0.391->0.367). Both
# modules stay in the tree for when full QA/coverage evaluation is added;
# no call site is wired here between the typed-pool and final stages,
# matching their position in pg_recall.py before the #368-family split.


def apply_final_stages(candidates: list[dict], ctx: RecallContext) -> list[dict]:
    """Event-order rerank, Titans test-time update, tail-mode SA fill.

    Order matters: chronological rerank only for EVENT_ORDER queries
    (ChronoRAG, Chen et al. 2025), then Titans test-time learning (Behrouz
    et al., NeurIPS 2025 — updates M/S via the paper's exact equations),
    then the TAIL mode SA fill LAST (ADR-0054 addendum) so an appended
    candidate can never be picked up and moved by an earlier stage. Tail
    fill only runs when fewer than ``top_k`` candidates were returned —
    zero store calls once the pipeline already filled ``top_k``.
    """
    if ctx.intent == QueryIntent.EVENT_ORDER and len(candidates) > 1:
        candidates = _chronological_rerank(candidates, beta=0.5, k=60)

    if ctx.momentum_state is not None:
        titans = _get_titans()
        result_embs = []
        for r in candidates[:10]:
            mem = ctx.store.get_memory(r["memory_id"])
            if mem and mem.get("embedding"):
                result_embs.append(mem["embedding"])
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

    Kept out of ``pg_recall.recall()`` itself so that function stays a
    stable, thin public-API wrapper (docstring + signature + one context
    construction) regardless of how many stages this pipeline grows — see
    pg_recall_context.py's ``RecallContext``/``fetch_and_triage`` for the
    per-parameter rationale and citations.
    """
    top_k = ctx.top_k
    candidates, ctx, early_return = fetch_and_triage(ctx)
    if early_return:
        return candidates[:top_k]

    candidates = apply_recollection_pipeline(candidates, ctx)
    candidates = apply_rerank_nudges(candidates, ctx)
    candidates = reserve_typed_pool(candidates, ctx)
    candidates = apply_final_stages(candidates, ctx)
    return candidates[:top_k]
