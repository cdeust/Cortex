"""Decay cycle: cool all memories and entities based on elapsed time.

Includes domain-aware astrocyte metabolic modulation via tripartite synapse.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.decay_cycle import compute_decay_updates, compute_entity_decay
from mcp_server.core.tripartite_calcium import (
    apply_metabolic_modulation,
    compute_heterosynaptic_depression,
)
from mcp_server.core.tripartite_synapse import (
    AstrocyteTerritory,
    update_territory,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_decay_cycle(store: MemoryStore, settings: Any) -> dict:
    """Apply heat decay to all active memories and entities."""
    memories = store.get_all_memories_for_decay()

    updates = compute_decay_updates(
        memories,
        decay_factor=settings.DECAY_FACTOR,
        importance_decay_factor=settings.IMPORTANCE_DECAY_FACTOR,
        emotional_decay_resistance=settings.EMOTIONAL_DECAY_RESISTANCE,
        cold_threshold=settings.COLD_THRESHOLD,
    )

    for mem_id, new_heat in updates:
        store.update_memory_heat(mem_id, new_heat)

    entity_updates = _decay_entities(store, settings)
    metabolic_updates = _apply_metabolic_modulation(
        store,
        settings,
        memories,
    )

    return {
        "memories_decayed": len(updates),
        "metabolic_updates": metabolic_updates,
        "entities_decayed": len(entity_updates),
        "total_memories": len(memories),
    }


def _decay_entities(
    store: MemoryStore,
    settings: Any,
) -> list[tuple[int, float]]:
    """Cool entity heat values."""
    entities = store.get_all_entities(min_heat=settings.COLD_THRESHOLD)
    entity_updates = compute_entity_decay(
        entities,
        decay_factor=0.98,
        cold_threshold=settings.COLD_THRESHOLD,
    )
    for eid, new_heat in entity_updates:
        store._conn.execute(
            "UPDATE entities SET heat = %s WHERE id = %s",
            (new_heat, eid),
        )
    if entity_updates:
        store._conn.commit()
    return entity_updates


def _apply_metabolic_modulation(
    store: MemoryStore,
    settings: Any,
    memories: list[dict],
) -> int:
    """Apply tripartite synapse metabolic modulation per domain."""
    metabolic_updates = 0
    try:
        domain_groups = _group_by_domain(memories)
        for domain, mems in domain_groups.items():
            metabolic_updates += _modulate_domain(
                store,
                settings,
                domain,
                mems,
            )
    except Exception:
        pass
    return metabolic_updates


def _group_by_domain(memories: list[dict]) -> dict[str, list]:
    """Group memories by their domain field."""
    groups: dict[str, list] = {}
    for mem in memories:
        d = mem.get("domain", "default") or "default"
        groups.setdefault(d, []).append(mem)
    return groups


def _modulate_domain(
    store: MemoryStore,
    settings: Any,
    domain: str,
    mems: list[dict],
) -> int:
    """Apply heterosynaptic depression for a single domain territory."""
    territory = AstrocyteTerritory(
        territory_id=domain,
        domain=domain,
        total_activity=sum(m.get("access_count", 0) for m in mems),
    )
    territory = update_territory(
        territory,
        synaptic_events=len(mems),
        hours_elapsed=1.0,
    )
    apply_metabolic_modulation(settings.DECAY_FACTOR, territory.metabolic_rate)

    mem_heats = [m.get("heat", 0.5) for m in mems]
    adjustments = compute_heterosynaptic_depression(
        territory.calcium,
        mem_heats,
    )

    count = 0
    for mem, adj in zip(mems, adjustments):
        if adj < 0.99:
            new_heat = max(0.0, mem.get("heat", 0.5) * adj)
            store.update_memory_heat(mem["id"], round(new_heat, 4))
            count += 1
    return count
