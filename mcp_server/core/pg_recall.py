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
from mcp_server.core.thermodynamics import (
    compute_heat_adjustment,
    compute_retrieval_surprise,
)

# ── PG weight profiles ──────────────────────────────────────────────────

_BASE_PG_WEIGHTS: dict[str, float] = {
    "vector": 1.0,
    "fts": 0.5,
    "bm25": 0.4,
    "heat": 0.3,
    "ngram": 0.3,
    "recency": 0.0,
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
    # The core_weights may reduce vector for intents like ENTITY (0.5) because
    # the 9-signal system compensates with entity/spreading signals. The PG
    # stored procedure has no such signals, so vector must stay at full strength.
    base = {
        "vector": 1.0,
        "fts": cw.get("fts", 0.5),
        "bm25": cw.get("fts", 0.5) * 0.8,
        "heat": cw.get("heat", 0.3),
        "ngram": cw.get("fts", 0.5) * 0.6,
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
    rerank_alpha: float = 0.55,
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
        rerank_alpha: Blend weight for cross-encoder scores.
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

    # 6. Titans surprise momentum
    if momentum_state is not None:
        _apply_surprise_momentum(q_emb, candidates[:top_k], store, momentum_state)

    return candidates[:top_k]


def _apply_surprise_momentum(
    q_emb: bytes | None,
    results: list[dict[str, Any]],
    store: Any,
    state: dict,
) -> None:
    """Update heat of retrieved memories based on retrieval surprise."""
    if not q_emb or not results:
        return
    result_embs = []
    for r in results[:10]:
        mem = store.get_memory(r["memory_id"])
        if mem and mem.get("embedding"):
            result_embs.append(mem["embedding"])
    if not result_embs:
        return
    surprise = compute_retrieval_surprise(q_emb, result_embs)
    prev = state.get("momentum", 0.5)
    state["momentum"] = 0.7 * prev + 0.3 * surprise
    adj = compute_heat_adjustment(surprise, state["momentum"], delta=0.08)
    if abs(adj) < 0.001:
        return
    for r in results:
        old_heat = r.get("heat", 0.5)
        new_heat = max(0.0, min(1.0, old_heat + adj))
        if abs(new_heat - old_heat) > 0.001:
            store.update_memory_heat(r["memory_id"], new_heat)
