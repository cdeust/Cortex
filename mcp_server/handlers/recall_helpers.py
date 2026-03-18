"""Helpers for the recall handler — signal collection and result building.

Extracted to keep recall.py under 300 lines with all methods under 40 lines.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_server.core import thermodynamics
from mcp_server.core.enrichment import build_expanded_query
from mcp_server.core.query_intent import QueryIntent
from mcp_server.core.retrieval_signals import (
    compute_hopfield_hdc,
    compute_graph_signals,
)
from mcp_server.core.scoring import compute_bm25_scores, compute_ngram_score
from mcp_server.core.temporal import compute_recency_boost
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


def compute_vector_fts(
    query: str,
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    pool: int,
    min_heat: float,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]], Any]:
    """Vector similarity + FTS5 signals."""
    q_emb = embeddings.encode(query)
    vec: list[tuple[int, float]] = []
    if q_emb:
        vec = [
            (m, 1.0 / (1.0 + d))
            for m, d in store.search_vectors(q_emb, top_k=pool, min_heat=min_heat)
        ]
    expanded = build_expanded_query(query)
    fts = store.search_fts(expanded, limit=pool)
    if expanded != query:
        ids = {m for m, _ in fts}
        fts.extend(
            (m, s) for m, s in store.search_fts(query, limit=pool // 2) if m not in ids
        )
    return vec, fts, q_emb


def compute_text_signals(
    query: str,
    hot_mems: list[dict],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """BM25 + n-gram signals from hot memory pool."""
    if not hot_mems:
        return [], []
    ids = [m["id"] for m in hot_mems]
    docs = [m.get("content", "") for m in hot_mems]
    bm25 = [(mid, s) for mid, s in zip(ids, compute_bm25_scores(query, docs)) if s > 0]
    ngram = [
        (m["id"], compute_ngram_score(query, m.get("content", ""))) for m in hot_mems
    ]
    return bm25, [(mid, s) for mid, s in ngram if s > 0]


def get_hot_pool(
    store: MemoryStore,
    domain: str | None,
    directory: str | None,
    min_heat: float,
    pool: int,
) -> list[dict]:
    """Fetch hot memories scoped by domain/directory."""
    if domain:
        return store.get_memories_for_domain(domain, min_heat=min_heat, limit=pool)
    if directory:
        return store.get_memories_for_directory(directory, min_heat=min_heat)
    return store.get_hot_memories(min_heat=min_heat, limit=pool)


def collect_signals(
    query: str,
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    settings: Any,
    pool: int,
    min_heat: float,
    domain: str | None,
    directory: str | None,
) -> dict[str, list]:
    """Collect all 9 retrieval signals."""
    vec, fts, q_emb = compute_vector_fts(query, store, embeddings, pool, min_heat)
    hot = get_hot_pool(store, domain, directory, min_heat, pool)
    hop, hdc = compute_hopfield_hdc(
        query, q_emb, store, embeddings, hot, settings, pool, min_heat
    )
    sr, sa = compute_graph_signals(query, store, vec, min_heat, settings, pool)
    bm25, ngram = compute_text_signals(query, hot)
    return {
        "vector": vec,
        "fts": fts,
        "heat": [(m["id"], m["heat"]) for m in hot],
        "hopfield": hop,
        "hdc": hdc,
        "sr": sr,
        "sa": sa,
        "bm25": bm25,
        "ngram": ngram,
    }


def compute_result_boost(intent: str, created_at: str, settings: Any) -> float:
    """Compute recency boost based on query intent."""
    if intent == QueryIntent.KNOWLEDGE_UPDATE:
        return compute_recency_boost(
            created_at,
            boost_max=settings.RECENCY_BOOST_MAX * 3.0,
            halflife_days=settings.RECENCY_BOOST_HALFLIFE_DAYS * 0.5,
            cutoff_days=settings.RECENCY_BOOST_CUTOFF_DAYS * 2.0,
        )
    return compute_recency_boost(
        created_at,
        boost_max=settings.RECENCY_BOOST_MAX,
        halflife_days=settings.RECENCY_BOOST_HALFLIFE_DAYS,
        cutoff_days=settings.RECENCY_BOOST_CUTOFF_DAYS,
    )


def parse_tags(tags: Any) -> list:
    """Normalize tags from string or list form."""
    if isinstance(tags, str):
        try:
            return json.loads(tags)
        except (ValueError, TypeError):
            return []
    return tags if tags else []


def build_result(mem: dict, score: float, intent: str, settings: Any) -> dict:
    """Build a single result dict with recency boost."""
    created_at = mem.get("created_at", "")
    heat = thermodynamics.compute_session_coherence(
        mem["heat"],
        created_at,
        bonus=settings.SESSION_COHERENCE_BONUS,
        window_hours=settings.SESSION_COHERENCE_WINDOW_HOURS,
    )
    boost = compute_result_boost(intent, created_at, settings)
    return {
        "memory_id": mem["id"],
        "content": mem["content"],
        "score": round(score * (1.0 + boost), 4),
        "heat": round(heat, 4),
        "domain": mem.get("domain", ""),
        "tags": parse_tags(mem.get("tags", [])),
        "store_type": mem.get("store_type", "episodic"),
        "created_at": created_at,
        "importance": mem.get("importance", 0.5),
        "surprise": mem.get("surprise_score", 0.0),
        "recency_boost": round(boost, 4),
    }


def build_enhancements(query: str, intent: str, tier: str, settings: Any) -> dict:
    """Build the enhancements metadata for the response."""
    return {
        "query_expanded": build_expanded_query(query) != query,
        "multihop_applied": tier == "mixed",
        "reranked": True,
        "knowledge_update_boost": intent == QueryIntent.KNOWLEDGE_UPDATE,
        "strategic_ordering": settings.STRATEGIC_ORDERING_ENABLED,
    }
