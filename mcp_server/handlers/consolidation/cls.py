"""CLS cycle: episodic -> semantic pattern extraction.

Includes causal edge discovery from entity co-occurrences via the PC algorithm.
"""

from __future__ import annotations

import logging

from mcp_server.core.causal_graph import (
    compute_co_occurrence_matrix,
    discover_causal_edges,
)
from mcp_server.core.consolidation_engine import plan_cls_consolidation
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

_EMPTY_CLS_STATS = {
    "patterns_found": 0,
    "new_semantics_created": 0,
    "skipped_inconsistent": 0,
    "skipped_duplicate": 0,
}


def run_cls_cycle(
    store: MemoryStore,
    settings,
    embeddings: EmbeddingEngine,
) -> dict:
    """Run CLS consolidation: episodic -> semantic pattern extraction."""
    episodic = store.get_episodic_memories(limit=500)
    existing_semantics = store.get_semantic_memories(limit=500)

    if not episodic:
        return _EMPTY_CLS_STATS.copy()

    plan = _compute_consolidation_plan(episodic, existing_semantics, embeddings)
    created = _create_semantic_memories(store, embeddings, plan)
    causal_edges_found = _discover_causal_edges(store, episodic)

    return {
        "patterns_found": plan["patterns_found"],
        "new_semantics_created": created,
        "skipped_inconsistent": plan["skipped_inconsistent"],
        "skipped_duplicate": plan["skipped_duplicate"],
        "causal_edges_found": causal_edges_found,
    }


def _compute_consolidation_plan(
    episodic: list[dict],
    existing_semantics: list[dict],
    embeddings: EmbeddingEngine,
) -> dict:
    """Plan which episodic memories to consolidate into semantics."""

    def similarity_fn(emb_a, emb_b) -> float:
        if emb_a is None or emb_b is None:
            return 0.0
        return embeddings.similarity(emb_a, emb_b)

    return plan_cls_consolidation(
        episodic_memories=episodic,
        existing_semantics=existing_semantics,
        similarity_fn=similarity_fn,
        cluster_threshold=0.6,
        dedup_threshold=0.85,
        min_occurrences=3,
        min_sessions=2,
    )


def _create_semantic_memories(
    store: MemoryStore,
    embeddings: EmbeddingEngine,
    plan: dict,
) -> int:
    """Create new semantic memories from the consolidation plan."""
    created = 0
    for semantic in plan["new_semantics"]:
        try:
            emb = embeddings.encode(semantic["schema"])
            mem_id = store.insert_memory(
                {
                    "content": semantic["schema"],
                    "embedding": emb,
                    "tags": semantic["tags"],
                    "domain": "",
                    "directory": "",
                    "source": "cls-consolidation",
                    "importance": 0.7,
                    "surprise": 0.0,
                    "emotional_valence": 0.0,
                    "confidence": 0.8,
                    "heat": 0.6,
                    "store_type": "semantic",
                }
            )
            _link_source_memories(store, mem_id, semantic["source_memory_ids"])
            created += 1
        except Exception:
            logger.exception("Failed to create semantic memory")
    return created


def _link_source_memories(
    store: MemoryStore,
    mem_id: int,
    source_ids: list,
) -> None:
    """Link source episodic memories to the new semantic memory."""
    for source_id in source_ids:
        if source_id is None:
            continue
        try:
            store.insert_relationship(
                {
                    "source_entity_id": source_id,
                    "target_entity_id": mem_id,
                    "relationship_type": "derived_from",
                    "weight": 1.0,
                    "confidence": 0.8,
                }
            )
        except Exception:
            pass


def _discover_causal_edges(
    store: MemoryStore,
    episodic: list[dict],
) -> int:
    """Discover causal edges from entity co-occurrences."""
    try:
        all_entities = store.get_all_entities(min_heat=0.0)
        entity_names = [e["name"] for e in all_entities if e.get("name")]
        if not entity_names or not episodic:
            return 0

        co_matrix = compute_co_occurrence_matrix(episodic, entity_names)
        entity_counts = _count_entity_mentions(entity_names, episodic)
        edges = discover_causal_edges(
            entity_names,
            co_matrix,
            entity_counts,
            len(episodic),
            min_observations=3,
            independence_threshold=0.5,
        )
        return _store_causal_edges(store, all_entities, edges)
    except Exception:
        logger.debug("Causal discovery failed (non-fatal)")
        return 0


def _count_entity_mentions(
    entity_names: list[str],
    episodic: list[dict],
) -> dict[str, int]:
    """Count how many episodic memories mention each entity."""
    counts: dict[str, int] = {}
    for name in entity_names:
        counts[name] = sum(
            1 for m in episodic if name.lower() in (m.get("content") or "").lower()
        )
    return counts


def _store_causal_edges(
    store: MemoryStore,
    all_entities: list[dict],
    edges: list[dict],
) -> int:
    """Persist discovered causal edges as relationships."""
    count = 0
    for edge in edges:
        try:
            src = [e for e in all_entities if e["name"] == edge["source"]]
            tgt = [e for e in all_entities if e["name"] == edge["target"]]
            if not src or not tgt:
                continue
            store.insert_relationship(
                {
                    "source_entity_id": src[0]["id"],
                    "target_entity_id": tgt[0]["id"],
                    "relationship_type": (
                        "causes" if edge["is_directed"] else "correlates_with"
                    ),
                    "weight": edge["strength"],
                    "confidence": 0.6 if edge["is_directed"] else 0.3,
                }
            )
            count += 1
        except Exception:
            pass
    return count
