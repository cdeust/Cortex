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

# Source: issue #13 — previous cap of 500 saw ~2% of a 25k-episodic
# store and produced 0 patterns by construction. 2000 matches plasticity
# sampling and keeps PC algorithm's O(E^2) worst case tractable on a
# 10k-entity vocabulary.
_EPISODIC_SAMPLE_CAP = 2000
_SEMANTICS_SAMPLE_CAP = 2000

_EMPTY_CLS_STATS = {
    "patterns_found": 0,
    "new_semantics_created": 0,
    "skipped_inconsistent": 0,
    "skipped_duplicate": 0,
    "causal_edges_found": 0,
    "episodic_scanned": 0,
}


def run_cls_cycle(
    store: MemoryStore,
    settings,
    embeddings: EmbeddingEngine,
) -> dict:
    """Run CLS consolidation: episodic → semantic pattern extraction.

    Pattern extraction (`plan_cls_consolidation`) and causal-edge
    discovery (`_discover_causal_edges`) sample up to 2000 episodic
    memories each — raised from 500 after Feynman's audit of darval's
    66K run in issue #13 showed 500 sampled 2% of the episodic store
    and produced 0 patterns by construction.
    """
    episodic = store.get_episodic_memories(limit=_EPISODIC_SAMPLE_CAP)
    existing_semantics = store.get_semantic_memories(limit=_SEMANTICS_SAMPLE_CAP)

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
        "episodic_scanned": len(episodic),
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
    """Discover causal edges from entity co-occurrences (PC algorithm).

    Gates on minimum signal before running the O(E²) independence tests:
    the PC algorithm needs at least `min_observations` mentions per
    entity in the sample to distinguish correlation from chance, so if
    fewer than `_MIN_ENTITIES_FOR_PC` entities clear that threshold,
    skip the analysis entirely (issue #13 Phase D).
    """
    try:
        all_entities = store.get_all_entities(min_heat=0.0)
        entity_names = [e["name"] for e in all_entities if e.get("name")]
        if not entity_names or not episodic:
            return 0

        entity_counts = _count_entity_mentions(entity_names, episodic)
        qualifying = sum(1 for c in entity_counts.values() if c >= _PC_MIN_OBSERVATIONS)
        if qualifying < _MIN_ENTITIES_FOR_PC:
            # Insufficient signal — don't run the full O(E^2) pass.
            return 0

        # Restrict the vocabulary to entities that meet the minimum, so
        # the co-occurrence matrix is E_qualifying^2, not E_all^2.
        active_names = [
            n for n in entity_names if entity_counts[n] >= _PC_MIN_OBSERVATIONS
        ]
        co_matrix = compute_co_occurrence_matrix(episodic, active_names)
        active_counts = {n: entity_counts[n] for n in active_names}
        edges = discover_causal_edges(
            active_names,
            co_matrix,
            active_counts,
            len(episodic),
            min_observations=_PC_MIN_OBSERVATIONS,
            independence_threshold=0.5,
        )
        return _store_causal_edges(store, all_entities, edges)
    except Exception as exc:
        logger.warning("Causal discovery failed: %s", exc, exc_info=True)
        return 0


# Source: PC algorithm lower bound — need ≥3 observations per variable
# to distinguish dependence from sampling noise; need ≥5 active variables
# for the independence tests to produce any non-trivial edge.
_PC_MIN_OBSERVATIONS = 3
_MIN_ENTITIES_FOR_PC = 5


def _count_entity_mentions(
    entity_names: list[str],
    episodic: list[dict],
) -> dict[str, int]:
    """Count how many episodic memories mention each entity.

    Single pass over the episodic sample with precomputed lowercase
    content and lowercase entity names (replaces the old O(N_ep × N_ent)
    loop that called .lower() on every cell).
    """
    content_lowered = [(m.get("content") or "").lower() for m in episodic]
    counts: dict[str, int] = {}
    for name in entity_names:
        name_l = name.lower()
        counts[name] = sum(1 for c in content_lowered if name_l in c)
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
