"""Handler: recall -- 3-tier dispatch + 9-signal WRRF fusion.

Composition root wiring infrastructure to core retrieval logic.
Tiers: simple (general), mixed (multi-hop), deep (entity/factual).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import memory_rules
from mcp_server.core.query_intent import classify_query_intent, QueryIntent
from mcp_server.core.retrieval_dispatch import dispatch_retrieval, wrrf_fuse
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

from mcp_server.handlers.recall_helpers import (
    compute_vector_fts,
    get_hot_pool,
    collect_signals,
    build_result,
    build_enhancements,
)

schema = {
    "description": "Retrieve memories using 3-tier dispatch with 9-signal WRRF fusion.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for"},
            "domain": {"type": "string", "description": "Restrict to specific domain"},
            "directory": {
                "type": "string",
                "description": "Restrict to specific directory",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results (default 10)",
            },
            "min_heat": {
                "type": "number",
                "description": "Minimum heat threshold (default 0.05)",
            },
        },
        "required": ["query"],
    },
}

_store: MemoryStore | None = None
_embeddings: EmbeddingEngine | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _get_embeddings() -> EmbeddingEngine:
    global _embeddings
    if _embeddings is None:
        _embeddings = EmbeddingEngine(dim=get_memory_settings().EMBEDDING_DIM)
    return _embeddings


def _apply_strategic_ordering(
    results: list[dict],
    top_fraction: float = 0.3,
    bottom_fraction: float = 0.2,
) -> list[dict]:
    """Reorder to mitigate 'Lost in the Middle' (Liu et al. 2023)."""
    n = len(results)
    if n < 5:
        return results
    top_n = max(1, int(n * top_fraction))
    bottom_n = max(1, int(n * bottom_fraction))
    if n - top_n - bottom_n <= 0:
        return results
    return results[:top_n] + results[n - bottom_n :] + results[top_n : n - bottom_n]


def _fetch_and_boost(
    fused: list[tuple[int, float]],
    store: MemoryStore,
    intent: str,
    settings: Any,
    max_results: int,
) -> list[dict]:
    """Fetch full memories and apply recency boost."""
    results = []
    for mem_id, score in fused[: max_results * 2]:
        mem = store.get_memory(mem_id)
        if mem is None:
            continue
        store.update_memory_access(mem_id)
        results.append(build_result(mem, score, intent, settings))
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def _apply_rules_and_order(
    results: list[dict], store: MemoryStore, settings: Any, max_results: int
) -> list[dict]:
    """Apply neuro-symbolic rules and strategic ordering."""
    try:
        rules = store.get_all_active_rules()
        if rules:
            results = memory_rules.apply_rules(results, rules, score_field="score")
    except Exception:
        pass
    results = results[:max_results]
    if settings.STRATEGIC_ORDERING_ENABLED:
        results = _apply_strategic_ordering(
            results, settings.STRATEGIC_TOP_FRACTION, settings.STRATEGIC_BOTTOM_FRACTION
        )
    return results


def _make_hop_fn(
    store: MemoryStore, emb: EmbeddingEngine, settings: Any, pool: int, min_heat: float
):
    """Create multi-hop sub-query function for dispatch."""

    def _hop(sq: str) -> list[tuple[int, float]]:
        sv, sf, _ = compute_vector_fts(sq, store, emb, pool // 2, min_heat)
        return wrrf_fuse(
            [sv, sf],
            [settings.WRRF_VECTOR_WEIGHT, settings.WRRF_FTS_WEIGHT],
            k=settings.WRRF_K,
        )

    return _hop


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retrieve memories using 3-tier dispatch + 9-signal WRRF fusion."""
    if not args or not args.get("query"):
        return {"results": [], "total": 0}

    query = args["query"]
    domain, directory = args.get("domain"), args.get("directory")
    max_results = args.get("max_results", 10)
    min_heat = args.get("min_heat", 0.05)
    settings = get_memory_settings()
    store, emb = _get_store(), _get_embeddings()
    pool = max_results * settings.WRRF_CANDIDATE_MULTIPLIER
    intent_info = classify_query_intent(query)
    intent = intent_info.get("intent", QueryIntent.GENERAL)

    signals = collect_signals(
        query, store, emb, settings, pool, min_heat, domain, directory
    )
    hot = get_hot_pool(store, domain, directory, min_heat, pool)
    content = {m["id"]: m.get("content", "") for m in hot} if hot else {}

    fused, tier = dispatch_retrieval(
        query=query,
        signals=signals,
        intent_info=intent_info,
        content_lookup=content,
        wrrf_k=settings.WRRF_K,
        base_vector_w=settings.WRRF_VECTOR_WEIGHT,
        base_fts_w=settings.WRRF_FTS_WEIGHT,
        base_heat_w=settings.WRRF_HEAT_WEIGHT,
        max_results=max_results,
        hop_fn=_make_hop_fn(store, emb, settings, pool, min_heat),
    )

    results = _fetch_and_boost(fused, store, intent, settings, max_results)
    results = _apply_rules_and_order(results, store, settings, max_results)
    return {
        "results": results,
        "total": len(results),
        "query_intent": intent,
        "dispatch_tier": tier,
        "signals": {n: len(signals.get(n, [])) for n in signals},
        "enhancements": build_enhancements(query, intent, tier, settings),
    }
