"""Plasticity cycle: Hebbian LTP/LTD on knowledge graph edges.

Strengthens co-accessed entity relationships and weakens unused ones
using BCM sliding threshold dynamics.
"""

from __future__ import annotations

import logging

from mcp_server.core.synaptic_plasticity import apply_hebbian_update
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_plasticity_cycle(store: MemoryStore) -> dict:
    """Apply Hebbian LTP/LTD to knowledge graph edges."""
    try:
        entities = store.get_all_entities(min_heat=0.0)
        relationships = store.get_all_relationships()

        if not entities or not relationships:
            return {"ltp": 0, "ltd": 0, "edges_updated": 0}

        activities, thresholds = _build_entity_maps(entities)
        co_accessed = _find_co_accessed_pairs(store, entities)
        edge_dicts = _format_edges(relationships)

        results = apply_hebbian_update(
            edge_dicts,
            co_accessed,
            activities,
            thresholds,
            hours_since_last_update=1.0,
        )

        ltp_count, ltd_count = _apply_updates(store, results)
        return {
            "ltp": ltp_count,
            "ltd": ltd_count,
            "edges_updated": ltp_count + ltd_count,
        }
    except Exception:
        logger.debug("Plasticity cycle failed (non-fatal)")
        return {"ltp": 0, "ltd": 0, "edges_updated": 0}


def _build_entity_maps(
    entities: list[dict],
) -> tuple[dict[int, float], dict[int, float]]:
    """Build activity and BCM threshold maps from entity data."""
    activities: dict[int, float] = {}
    thresholds: dict[int, float] = {}
    for ent in entities:
        eid = ent["id"]
        heat = ent.get("heat", 0.5)
        access = ent.get("access_count", 0)
        activities[eid] = min(1.0, heat + access * 0.01)
        thresholds[eid] = 0.3 + heat * 0.4
    return activities, thresholds


def _find_co_accessed_pairs(
    store: MemoryStore,
    entities: list[dict],
) -> set[tuple[int, int]]:
    """Determine co-accessed entity pairs from recent memories."""
    recent = store.get_hot_memories(min_heat=0.1, limit=50)
    co_accessed: set[tuple[int, int]] = set()

    for mem in recent:
        content_lower = (mem.get("content") or "").lower()
        mem_entities = [
            e["id"]
            for e in entities
            if e.get("name") and e["name"].lower() in content_lower
        ]
        for i in range(len(mem_entities)):
            for j in range(i + 1, len(mem_entities)):
                pair = (
                    min(mem_entities[i], mem_entities[j]),
                    max(mem_entities[i], mem_entities[j]),
                )
                co_accessed.add(pair)

    return co_accessed


def _format_edges(relationships: list[dict]) -> list[dict]:
    """Format relationship rows into edge dicts for Hebbian update."""
    return [
        {
            "id": r["id"],
            "source_entity_id": r["source_entity_id"],
            "target_entity_id": r["target_entity_id"],
            "weight": r.get("weight", 1.0),
        }
        for r in relationships
    ]


def _apply_updates(
    store: MemoryStore,
    results: list[dict],
) -> tuple[int, int]:
    """Apply Hebbian weight updates to the store."""
    ltp_count = 0
    ltd_count = 0
    for r in results:
        if r["action"] == "none":
            continue
        store._conn.execute(
            "UPDATE relationships SET weight = ? WHERE id = ?",
            (r["weight"], r["id"]),
        )
        if r["action"] == "ltp":
            ltp_count += 1
        else:
            ltd_count += 1
    if ltp_count + ltd_count > 0:
        store._conn.commit()
    return ltp_count, ltd_count
