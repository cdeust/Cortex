"""Handler: recall -- 3-tier dispatch + 9-signal WRRF fusion.

Composition root wiring infrastructure to core retrieval logic.
Tiers: simple (general), mixed (multi-hop), deep (entity/factual).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import memory_rules
from mcp_server.core.knowledge_graph import extract_entities
from mcp_server.core.query_intent import classify_query_intent, QueryIntent
from mcp_server.core.retrieval_dispatch import dispatch_retrieval, wrrf_fuse
from mcp_server.core.thermodynamics import (
    compute_retrieval_surprise,
    compute_heat_adjustment,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

from mcp_server.handlers.recall_helpers import (
    compute_vector_fts,
    get_hot_pool,
    collect_signals,
    build_result,
    build_enhancements,
    inject_triggered_memories,
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
_momentum: dict[str, float] = {}  # domain -> momentum (Titans test-time learning)


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


def _apply_surprise_momentum(
    results: list[dict],
    q_emb: Any,
    store: MemoryStore,
    settings: Any,
    domain: str | None,
) -> None:
    """Titans-inspired test-time learning: update heat based on retrieval surprise."""
    if not settings.SURPRISE_MOMENTUM_ENABLED or not results or not q_emb:
        return
    result_embs = [r.get("embedding") for r in results if r.get("embedding")]
    if not result_embs:
        # Fetch embeddings for surprise computation
        result_embs = []
        for r in results[:10]:
            mem = store.get_memory(r["memory_id"])
            if mem and mem.get("embedding"):
                result_embs.append(mem["embedding"])
    surprise = compute_retrieval_surprise(q_emb, result_embs)
    key = domain or "_global"
    prev = _momentum.get(key, 0.5)
    _momentum[key] = (
        settings.SURPRISE_MOMENTUM_ETA * prev
        + (1 - settings.SURPRISE_MOMENTUM_ETA) * surprise
    )
    adj = compute_heat_adjustment(
        surprise, _momentum[key], settings.SURPRISE_MOMENTUM_DELTA
    )
    if abs(adj) < 0.001:
        return
    for r in results:
        new_heat = max(0.0, min(1.0, r["heat"] + adj))
        if abs(new_heat - r["heat"]) > 0.001:
            store.update_memory_heat(r["memory_id"], new_heat)
            r["heat"] = new_heat


def _apply_co_activation(
    results: list[dict], store: MemoryStore, settings: Any
) -> None:
    """Dragon Hatchling Hebbian: co-retrieved entities strengthen edges."""
    if not settings.CO_ACTIVATION_ENABLED or len(results) < 2:
        return
    min_score = settings.CO_ACTIVATION_MIN_SCORE
    lr = settings.CO_ACTIVATION_LEARNING_RATE
    # Extract entities from top-5 results above min_score
    entity_sets: list[set[str]] = []
    for r in results[:5]:
        if r.get("score", 0) < min_score:
            continue
        ents = extract_entities(r.get("content", ""))
        entity_sets.append({e["name"] for e in ents})
    # Reinforce cross-memory entity pairs
    try:
        for i, ents_a in enumerate(entity_sets):
            for ents_b in entity_sets[i + 1 :]:
                for a in list(ents_a)[:5]:
                    for b in list(ents_b)[:5]:
                        if a != b:
                            store.reinforce_or_create_relationship(a, b, lr)
    except Exception:
        pass


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
    # Prospective memory: inject triggered standing instructions
    results = inject_triggered_memories(results, query, store)
    # Titans test-time learning: surprise momentum updates heat in PG
    q_emb = emb.encode(query[:500]) if emb else None
    _apply_surprise_momentum(results, q_emb, store, settings, domain)
    # Dragon Hatchling Hebbian: co-retrieved entities strengthen graph edges
    _apply_co_activation(results, store, settings)
    results = _apply_rules_and_order(results, store, settings, max_results)
    return {
        "results": results,
        "total": len(results),
        "query_intent": intent,
        "dispatch_tier": tier,
        "signals": {n: len(signals.get(n, [])) for n in signals},
        "enhancements": build_enhancements(query, intent, tier, settings),
    }
