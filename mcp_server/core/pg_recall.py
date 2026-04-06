"""PG recall: intent-adaptive retrieval via recall_memories() + FlashRank reranking.

Stateless retrieval function that orchestrates:
  1. Intent classification → PG signal weight profile
  2. PG recall_memories() stored procedure (server-side WRRF fusion)
  3. Client-side FlashRank cross-encoder reranking
  4. Titans surprise momentum (test-time heat updates)

Used by both the production recall handler and benchmarks — single source
of truth for PG-path retrieval.

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
}


def compute_pg_weights(
    intent: str, core_weights: dict | None = None
) -> dict[str, float]:
    """Compute PG recall_memories() signal weights for a given intent.

    Derives base weights from core_weights (from query_intent) when available,
    then applies intent-specific PG overrides.
    """
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

    # 3. Encode query
    q_emb = embeddings.encode(query[:500]) if embeddings else None

    # 4. PG recall_memories (server-side WRRF fusion)
    candidates = store.recall_memories(
        query_text=query,
        query_embedding=q_emb,
        intent=str(intent.value) if hasattr(intent, "value") else str(intent),
        domain=domain,
        directory=directory,
        agent_topic=agent_topic,
        min_heat=min_heat,
        max_results=top_k,
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

    # 6. Chronological reranking for event ordering queries.
    # ChronoRAG (Chen et al., 2025): blend relevance rank with
    # chronological rank via RRF (Cormack et al., 2009).
    # Only activates when intent is EVENT_ORDER.
    if intent == QueryIntent.EVENT_ORDER and len(candidates) > 1:
        candidates = _chronological_rerank(candidates, beta=0.5, k=60)

    # 7. Titans test-time learning (Behrouz et al., NeurIPS 2025)
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
