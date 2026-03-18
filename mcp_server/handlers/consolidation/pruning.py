"""Pruning cycle: microglial complement-dependent edge and entity elimination.

Weak edges are removed, and orphaned entities are archived (heat set to 0).
"""

from __future__ import annotations

import logging

from mcp_server.core.microglial_pruning import (
    identify_orphaned_entities,
    identify_prunable_edges,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_pruning_cycle(store: MemoryStore) -> dict:
    """Run microglial pruning: eliminate weak edges and orphaned entities."""
    try:
        entities = store.get_all_entities(min_heat=0.0)
        relationships = store.get_all_relationships()

        if not entities:
            return {"edges_pruned": 0, "entities_archived": 0}

        edge_dicts = _format_edges(relationships)
        entity_heat = {e["id"]: e.get("heat", 0) for e in entities}
        entity_protected = {
            e["id"]: bool(e.get("is_protected", False)) for e in entities
        }

        prunable = identify_prunable_edges(
            edge_dicts,
            entity_heat,
            entity_protected,
        )
        edges_pruned = _prune_edges(store, prunable)
        entities_archived = _archive_orphans(
            store,
            entities,
            relationships,
            prunable,
        )

        return {
            "edges_pruned": edges_pruned,
            "entities_archived": entities_archived,
        }
    except Exception:
        logger.debug("Pruning cycle failed (non-fatal)")
        return {"edges_pruned": 0, "entities_archived": 0}


def _format_edges(relationships: list[dict]) -> list[dict]:
    """Format relationship rows into edge dicts for the pruning core."""
    return [
        {
            "source_entity_id": r["source_entity_id"],
            "target_entity_id": r["target_entity_id"],
            "weight": r.get("weight", 1.0),
            "hours_since_co_access": 48,
            "id": r["id"],
        }
        for r in relationships
    ]


def _prune_edges(store: MemoryStore, prunable: list[dict]) -> int:
    """Delete prunable edges from the store."""
    count = 0
    for edge in prunable:
        try:
            store._conn.execute(
                "DELETE FROM relationships WHERE id = ?",
                (edge["id"],),
            )
            count += 1
        except Exception:
            pass
    if count:
        store._conn.commit()
    return count


def _archive_orphans(
    store: MemoryStore,
    entities: list[dict],
    relationships: list[dict],
    prunable: list[dict],
) -> int:
    """Find and archive orphaned entities after pruning."""
    pruned_ids = {e.get("id") for e in prunable}
    active_edge_entities = _collect_active_edge_entities(
        relationships,
        pruned_ids,
    )
    memory_entity_ids = _collect_memory_entity_ids(store, entities)

    orphans = identify_orphaned_entities(
        entities,
        active_edge_entities,
        memory_entity_ids,
    )

    count = 0
    for orphan in orphans:
        try:
            store._conn.execute(
                "UPDATE entities SET heat = 0 WHERE id = ?",
                (orphan["id"],),
            )
            count += 1
        except Exception:
            pass
    if count:
        store._conn.commit()
    return count


def _collect_active_edge_entities(
    relationships: list[dict],
    pruned_ids: set,
) -> set[int]:
    """Collect entity IDs still connected by non-pruned edges."""
    active: set[int] = set()
    for r in relationships:
        if r["id"] not in pruned_ids:
            active.add(r["source_entity_id"])
            active.add(r["target_entity_id"])
    return active


def _collect_memory_entity_ids(
    store: MemoryStore,
    entities: list[dict],
) -> set[int]:
    """Collect entity IDs mentioned in hot memories."""
    memory_entity_ids: set[int] = set()
    hot_mems = store.get_hot_memories(min_heat=0.01, limit=200)
    for ent in entities:
        name = ent.get("name", "")
        if not name:
            continue
        for m in hot_mems:
            if name.lower() in (m.get("content") or "").lower():
                memory_entity_ids.add(ent["id"])
                break
    return memory_entity_ids
