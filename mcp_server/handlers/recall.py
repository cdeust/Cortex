"""Handler: recall -- PG recall + production enrichments.

Composition root wiring infrastructure to core retrieval logic.

Base retrieval uses pg_recall (intent-adaptive PG WRRF + FlashRank reranking).
Production enrichments layer on top: prospective memory injection,
co-activation Hebbian learning, neuro-symbolic rules, strategic ordering.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import memory_rules
from mcp_server.core.knowledge_graph import extract_entities
from mcp_server.core.pg_recall import recall as pg_recall
from mcp_server.core.query_intent import QueryIntent, classify_query_intent
from mcp_server.handlers.recall_helpers import (
    build_enhancements,
    inject_triggered_memories,
)
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

schema = {
    "description": (
        "Retrieve memories from the Cortex store using intent-adaptive PG "
        "recall (server-side WRRF fusion of vector + FTS + trigram + heat + "
        "recency) followed by FlashRank cross-encoder reranking and "
        "production enrichments (prospective memory injection, Hebbian "
        "co-activation strengthening, neuro-symbolic rules, strategic ordering "
        "to mitigate Lost-in-the-Middle, Liu et al. 2023). Use this before "
        "any non-trivial work to check what Cortex already knows; running "
        "blind is unacceptable when recall takes ~200ms. Distinct from "
        "`recall_hierarchical` (returns the L0/L1/L2 cluster topology, not "
        "a flat ranked list), `navigate_memory` (graph BFS over co-access "
        "edges from one seed memory), and `get_causal_chain` (entity-graph "
        "traversal, not memory recall). Returns ranked memories with scores, "
        "heat, and source."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural-language query describing what to retrieve. Free "
                    "text; intent (temporal/causal/semantic/entity/multi-hop) "
                    "is auto-classified to weight the WRRF signals."
                ),
                "examples": [
                    "why did we choose pgvector over Pinecone?",
                    "failed attempts to fix recall regression",
                    "what does the consolidate handler do?",
                ],
            },
            "domain": {
                "type": "string",
                "description": (
                    "Restrict results to a single cognitive domain. Omit to "
                    "search across all domains."
                ),
                "examples": ["cortex", "auth-service"],
            },
            "directory": {
                "type": "string",
                "description": (
                    "Restrict results to memories tagged with a specific "
                    "absolute project directory."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of ranked memories to return after reranking."
                ),
                "default": 10,
                "minimum": 1,
                "maximum": 100,
                "examples": [5, 10, 25],
            },
            "min_heat": {
                "type": "number",
                "description": (
                    "Minimum heat (0.0-1.0) for a memory to be considered. "
                    "Lower = include colder/older memories. Use 0 to include everything."
                ),
                "default": 0.05,
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.0, 0.05, 0.3],
            },
            "agent_topic": {
                "type": "string",
                "description": (
                    "Restrict to memories produced under a specific agent "
                    "context tag (subagent topic isolation)."
                ),
                "examples": ["engineer", "researcher", "reviewer"],
            },
        },
    },
}

_store: MemoryStore | None = None
_momentum_state: dict = {"momentum": 0.5}


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


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


def _apply_co_activation(
    results: list[dict], store: MemoryStore, settings: Any
) -> None:
    """Dragon Hatchling Hebbian: co-retrieved entities strengthen edges."""
    if not settings.CO_ACTIVATION_ENABLED or len(results) < 2:
        return
    min_score = settings.CO_ACTIVATION_MIN_SCORE
    lr = settings.CO_ACTIVATION_LEARNING_RATE
    entity_sets: list[set[str]] = []
    for r in results[:5]:
        if r.get("score", 0) < min_score:
            continue
        ents = extract_entities(r.get("content", ""))
        entity_sets.append({e["name"] for e in ents})
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


def _track_recall_replay(results: list[dict], store: Any) -> None:
    """Increment access_count and replay_count for recalled memories.

    Each recall event counts as a hippocampal replay (McClelland 1995).
    This drives consolidation stage advancement through the cascade.
    """
    for mem in results:
        mem_id = mem.get("memory_id") or mem.get("id")
        if mem_id is None:
            continue
        try:
            store.update_memory_access(mem_id)
            store.increment_replay_count(mem_id)
        except Exception:
            pass


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Retrieve memories: pg_recall base + production enrichments."""
    if not args or not args.get("query"):
        return {"results": [], "total": 0}

    query = args["query"]
    domain, directory = args.get("domain"), args.get("directory")
    agent_topic = args.get("agent_topic")
    max_results = args.get("max_results", 10)
    min_heat = args.get("min_heat", 0.05)
    settings = get_memory_settings()
    store, emb = _get_store(), get_embedding_engine()

    # Base retrieval: pg_recall (intent → PG weights → recall_memories → rerank)
    results = pg_recall(
        query=query,
        store=store,
        embeddings=emb,
        top_k=max_results,
        domain=domain,
        directory=directory,
        agent_topic=agent_topic,
        min_heat=min_heat,
        wrrf_k=settings.WRRF_K,
        momentum_state=_momentum_state,
    )

    # Production enrichments on top of base retrieval
    results = inject_triggered_memories(results, query, store)
    _apply_co_activation(results, store, settings)
    results = _apply_rules_and_order(results, store, settings, max_results)

    # Track access + replay for consolidation cascade
    # Biological basis: retrieval = hippocampal replay (McClelland 1995)
    # Each recall increments replay_count, driving stage advancement
    _track_recall_replay(results, store)

    intent_info = classify_query_intent(query)
    intent = intent_info.get("intent", QueryIntent.GENERAL)
    return {
        "results": results,
        "total": len(results),
        "query_intent": intent,
        "dispatch_tier": "pg",
        "signals": {},
        "enhancements": build_enhancements(query, intent, "pg", settings),
    }
