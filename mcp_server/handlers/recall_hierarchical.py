"""Handler: recall_hierarchical — fractal memory tree retrieval.

Uses the 3-level fractal hierarchy (L0=memories, L1=clusters, L2=root clusters)
to retrieve memories with adaptive level weighting based on query length.

Short queries -> broad (L2-weighted).
Long queries  -> specific (L0-weighted).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import fractal
from mcp_server.infrastructure.embedding_engine import (
    EmbeddingEngine,
    get_embedding_engine,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Retrieve memories via the fractal three-level hierarchy (L0=individual "
        "memories, L1=topic clusters, L2=root clusters), with adaptive level "
        "weighting from query length: short queries weight toward broader L2 "
        "clusters (you're scanning a topic), long queries toward specific L0 "
        "memories (you have a precise question). Use this instead of `recall` "
        "when you want the topology of the memory space, not just a flat "
        "ranked list. Distinct from `recall` (flat WRRF result, no hierarchy), "
        "`drill_down` (consumer of this tool's output, navigates one level "
        "deeper into a returned cluster), and `navigate_memory` (graph "
        "traversal, not cluster tree). Mutates access_count on surfaced "
        "memories. Latency ~150-300ms. Returns {hierarchy: [{cluster_id, "
        "level, label, score, members?}], total_clusters}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language query. Length influences level weighting.",
                "examples": [
                    "recall regression",
                    "why did pgvector beat IVFFlat on small corpus",
                ],
            },
            "domain": {
                "type": "string",
                "description": "Restrict the hierarchy to a single cognitive domain.",
                "examples": ["cortex", "auth-service"],
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of memories returned across all levels.",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "examples": [5, 10, 25],
            },
            "min_heat": {
                "type": "number",
                "description": "Minimum heat (0.0-1.0) for a memory to be considered.",
                "default": 0.05,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.0, 0.05, 0.3],
            },
            "cluster_threshold": {
                "type": "number",
                "description": (
                    "Cosine-similarity threshold used when forming L1 clusters. "
                    "Higher = tighter clusters, more groups."
                ),
                "default": 0.6,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.5, 0.6, 0.75],
            },
        },
    },
}

# ── Singletons ────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Helpers ───────────────────────────────────────────────────────────────


def _fetch_candidate_memories(
    store: MemoryStore,
    domain: str,
    min_heat: float,
) -> list[dict]:
    """Fetch memories eligible for hierarchy building."""
    if domain:
        return store.get_memories_for_domain(domain, min_heat=min_heat, limit=500)

    all_mems = store.get_all_memories_for_decay()
    return [m for m in all_mems if m.get("heat", 0) >= min_heat]


def _enrich_results(
    raw_results: list[dict],
    store: MemoryStore,
    max_results: int,
) -> list[dict]:
    """Attach full memory data to scored results."""
    results = []
    for item in raw_results[:max_results]:
        mem = store.get_memory(item["memory_id"])
        if not mem:
            continue
        results.append(
            {
                "memory_id": item["memory_id"],
                "score": round(item["score"], 4),
                "matched_level": item["matched_level"],
                "level_scores": item.get("level_scores", {}),
                "content": mem["content"],
                "heat": round(mem.get("heat", 0.0), 4),
                "domain": mem.get("domain", ""),
                "tags": mem.get("tags", []),
                "created_at": mem.get("created_at", ""),
            }
        )
    return results


# ── Handler ───────────────────────────────────────────────────────────────


def _score_memories_against_hierarchy(
    memories: list[dict],
    query_embedding: list[float],
    query: str,
    embeddings: EmbeddingEngine,
    cluster_threshold: float,
    max_results: int,
) -> tuple[list[dict], dict]:
    """Build fractal hierarchy and score memories against it."""
    settings = get_memory_settings()
    hierarchy = fractal.build_hierarchy(
        memories=memories,
        similarity_fn=embeddings.similarity,
        embedding_dim=settings.EMBEDDING_DIM,
        l1_threshold=cluster_threshold,
    )
    raw_results = fractal.score_against_hierarchy(
        query_embedding=query_embedding,
        hierarchy=hierarchy,
        similarity_fn=embeddings.similarity,
        query=query,
        max_results=max_results * 2,
    )
    return raw_results, hierarchy


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retrieve memories using fractal hierarchy scoring."""
    if not args or not args.get("query"):
        return {"results": [], "total": 0, "hierarchy": {}}

    query = args["query"]
    domain = args.get("domain", "")
    max_results = args.get("max_results", 10)
    min_heat = args.get("min_heat", 0.05)
    cluster_threshold = float(args.get("cluster_threshold", 0.6))

    store = _get_store()
    embeddings = get_embedding_engine()

    memories = _fetch_candidate_memories(store, domain, min_heat)
    if not memories:
        return {"results": [], "total": 0, "hierarchy": {"stats": {}}}

    query_embedding = embeddings.encode(query)
    if not query_embedding:
        return {"results": [], "total": 0, "error": "embedding_unavailable"}

    # Filter memories that have embeddings (newly stored may lack them)
    memories_with_emb = [m for m in memories if m.get("embedding")]
    if len(memories_with_emb) < 3:
        # Too few embeddings for clustering — fall back to flat vector search
        from mcp_server.handlers.recall import handler as flat_recall

        return await flat_recall(args)

    raw_results, hierarchy = _score_memories_against_hierarchy(
        memories_with_emb,
        query_embedding,
        query,
        embeddings,
        cluster_threshold,
        max_results,
    )
    results = _enrich_results(raw_results, store, max_results)

    # Track replay for consolidation cascade
    for mem in results:
        mem_id = mem.get("memory_id") or mem.get("id")
        if mem_id is not None:
            try:
                store.update_memory_access(mem_id)
                store.increment_replay_count(mem_id)
            except Exception:
                pass

    return {
        "results": results,
        "total": len(results),
        "query_word_count": len(query.split()),
        "level_weights": dict(
            zip(["L0", "L1", "L2"], fractal.compute_level_weights(query))
        ),
        "hierarchy": {"stats": hierarchy.get("stats", {})},
    }
