"""Core post-storage operations — entity persistence, synaptic tagging, engrams.

Extracted from the remember handler to keep each function under 40 lines.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mcp_server.core import engram, knowledge_graph, prospective
from mcp_server.core.synaptic_tagging import apply_synaptic_tags as _apply_tags


def extract_triggers(
    content: str,
    directory: str,
    store: Any,
) -> list[int]:
    """Auto-extract prospective triggers and persist them."""
    intents = prospective.extract_prospective_intents(content)
    trigger_ids: list[int] = []
    for intent in intents:
        tid = store.insert_prospective_memory(
            {
                **intent,
                "target_directory": directory,
            }
        )
        trigger_ids.append(tid)
    return trigger_ids


def persist_entities(
    extracted_entities: list[dict],
    domain: str,
    content: str,
    store: Any,
) -> list[int]:
    """Insert new entities and co-occurrence relationships."""
    entity_ids: list[int] = []
    for ent in extracted_entities:
        existing = store.get_entity_by_name(ent["name"])
        if existing:
            entity_ids.append(existing["id"])
        else:
            eid = store.insert_entity(
                {
                    "name": ent["name"],
                    "type": ent["type"],
                    "domain": domain,
                }
            )
            entity_ids.append(eid)
    _create_co_occurrences(extracted_entities, content, store, entity_ids)
    return entity_ids


def _create_co_occurrences(
    entities: list[dict],
    content: str,
    store: Any,
    entity_ids: list[int],
) -> None:
    """Create co-occurrence relationships between extracted entities."""
    if len(entity_ids) < 2:
        return
    names = [e["name"] for e in entities]
    co_ocs = knowledge_graph.detect_co_occurrences(names, content)
    for name_a, name_b, proximity in co_ocs:
        ea = store.get_entity_by_name(name_a)
        eb = store.get_entity_by_name(name_b)
        if ea and eb:
            store.insert_relationship(
                {
                    "source_entity_id": ea["id"],
                    "target_entity_id": eb["id"],
                    "relationship_type": "co_occurrence",
                    "weight": proximity,
                }
            )


def run_synaptic_tagging(
    mem_id: int,
    importance: float,
    new_entity_names: list[str],
    store: Any,
) -> list[dict]:
    """Retroactively boost weak memories sharing entities (Frey & Morris 1997)."""
    tagged: list[dict] = []
    try:
        if importance < 0.7 or not new_entity_names:
            return tagged
        recent = store.get_hot_memories(min_heat=0.0, limit=50)
        candidates = _build_tagging_candidates(
            recent,
            mem_id,
            new_entity_names,
            store,
        )
        new_ent_set = {n.lower() for n in new_entity_names}
        tag_results = _apply_tags(
            new_memory_entities=new_ent_set,
            new_memory_importance=importance,
            existing_memories=candidates,
        )
        for tag in tag_results:
            store.update_memory_importance(tag["memory_id"], tag["new_importance"])
            store.update_memory_heat(tag["memory_id"], tag["new_heat"])
            tagged.append(tag)
    except Exception:
        pass
    return tagged


def _build_tagging_candidates(
    recent: list[dict],
    exclude_id: int,
    entity_names: list[str],
    store: Any,
) -> list[dict]:
    """Build candidate list for synaptic tagging evaluation."""
    candidates: list[dict] = []
    for mem in recent:
        if mem["id"] == exclude_id:
            continue
        mem_ents = _find_shared_entities(mem["id"], entity_names, store)
        hours_ago = _hours_since_creation(mem.get("created_at", ""))
        candidates.append(
            {
                "id": mem["id"],
                "importance": mem.get("importance", 0.5),
                "heat": mem.get("heat", 0.1),
                "entities": mem_ents,
                "age_hours": hours_ago,
            }
        )
    return candidates


def _find_shared_entities(
    mem_id: int,
    entity_names: list[str],
    store: Any,
) -> set[str]:
    """Find which entities a memory mentions."""
    mem_ents: set[str] = set()
    for ename in entity_names:
        mentioning = store.get_memories_mentioning_entity(ename, limit=50)
        if any(m["id"] == mem_id for m in mentioning):
            mem_ents.add(ename.lower())
    all_entities = store.get_all_entities(min_heat=0.0)
    for ent in all_entities:
        mentioning = store.get_memories_mentioning_entity(ent["name"], limit=50)
        if any(m["id"] == mem_id for m in mentioning):
            mem_ents.add(ent["name"].lower())
    return mem_ents


def _hours_since_creation(iso_str: str) -> float:
    """Parse creation timestamp and return hours elapsed."""
    if not iso_str:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return 0.0


def allocate_engram_slot(
    mem_id: int,
    settings: Any,
    store: Any,
) -> dict | None:
    """Allocate an engram slot for competitive memory allocation."""
    try:
        store.init_engram_slots(settings.HOPFIELD_MAX_PATTERNS)
        all_slots = store.get_all_engram_slots()
        if not all_slots:
            return None
        best_slot, best_exc = engram.find_best_slot(
            all_slots,
            settings.EXCITABILITY_HALF_LIFE_HOURS,
        )
        store.assign_memory_slot(mem_id, best_slot)
        new_exc = engram.compute_boost(best_exc, settings.EXCITABILITY_BOOST)
        store.update_engram_slot(best_slot, new_exc, store._now_iso())
        linked = store.get_memories_in_slot(best_slot)
        linked_ids = [m["id"] for m in linked if m["id"] != mem_id]
        return {
            "slot_index": best_slot,
            "temporally_linked": len(linked_ids),
        }
    except Exception:
        return None
