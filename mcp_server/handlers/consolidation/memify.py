"""Memify cycle: self-improvement via pruning, strengthening, and reweighting.

Prunes low-quality memories, boosts important ones, and adjusts relationship
weights based on entity heat.
"""

from __future__ import annotations

import logging

from mcp_server.core.curation import (
    compute_relationship_reweights,
    identify_prunable,
    identify_strengtheneable,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_memify_cycle(store: MemoryStore) -> dict:
    """Run memify self-improvement: prune, strengthen, reweight."""
    memories = store.get_all_memories_for_decay()

    pruned = _prune_memories(store, memories)
    strengthened = _strengthen_memories(store, memories)
    reweighted = _reweight_relationships(store)

    return {
        "pruned": pruned,
        "strengthened": strengthened,
        "reweighted": reweighted,
    }


def _prune_memories(store: MemoryStore, memories: list[dict]) -> int:
    """Delete prunable low-quality memories."""
    prunable_ids = identify_prunable(memories)
    count = 0
    for mid in prunable_ids:
        try:
            store.delete_memory(mid)
            count += 1
        except Exception:
            pass
    return count


def _strengthen_memories(store: MemoryStore, memories: list[dict]) -> int:
    """Boost importance of memories that deserve strengthening."""
    strengthen_list = identify_strengtheneable(memories)
    count = 0
    for mid, new_importance in strengthen_list:
        try:
            store.update_memory_importance(mid, new_importance)
            count += 1
        except Exception:
            pass
    return count


def _reweight_relationships(store: MemoryStore) -> int:
    """Adjust relationship weights based on entity heat."""
    from mcp_server.infrastructure.sql_compat import execute, commit, fetchall

    try:
        entities = store.get_all_entities(min_heat=0.0)
        entity_heats = {e["id"]: e.get("heat", 0.5) for e in entities}

        rels = fetchall(store._conn,
            "SELECT id, source_entity_id, target_entity_id, weight FROM relationships",
        )
        reweights = compute_relationship_reweights(rels, entity_heats)

        count = 0
        for rid, new_weight in reweights:
            execute(store._conn,
                "UPDATE relationships SET weight = %s WHERE id = %s",
                (new_weight, rid),
            )
            count += 1
        if count:
            commit(store._conn)
        return count
    except Exception:
        return 0
