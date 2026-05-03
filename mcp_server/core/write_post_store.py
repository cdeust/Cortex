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
    memory_id: int | None = None,
) -> list[int]:
    """Insert new entities, co-occurrence relationships, and memory-entity links."""
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
    # Persist memory-entity links in join table
    if memory_id is not None:
        for eid in entity_ids:
            store.insert_memory_entity(memory_id, eid)
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
        # Synaptic-tagging window is cadence-relative to ingest time, not
        # original-event time. For backfilled memories with a backdated
        # created_at this prevents the tagging window from collapsing
        # immediately on first consolidation pass.
        # Source: tasks/e1-v3-locomo-smoke-finding.md.
        hours_ago = _hours_since_creation(
            mem.get("ingested_at") or mem.get("created_at", "")
        )
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
    """Find which entities a memory mentions.

    Phase 2 B2: replaces the pre-Phase-2 O(N_candidates × 50) substring
    scan (via get_memories_mentioning_entity) with a single JOIN query
    on memory_entities. Requires the Phase 0.4.5 backfill (I4 coverage
    ≥ 99%); pre-backfill the JOIN would miss pairs. Falls back to the
    empty set on any error (caller handles "no shared entities").

    Source: docs/program/phase-5-pool-admission-design.md (Phase 2 B2);
            docs/invariants/cortex-invariants.md §I4.
    """
    if not mem_id:
        return set()

    # Resolve both the caller-supplied names and the full entity set
    # to IDs once. We need the full entity set because the caller
    # is asking "which entities does this memory mention from the
    # entire catalog", not just "from entity_names".
    id_to_name: dict[int, str] = {}
    try:
        for ename in entity_names or []:
            ent = store.get_entity_by_name(ename)
            if ent and ent.get("id") is not None:
                id_to_name[int(ent["id"])] = ename
        for ent in store.get_all_entities(min_heat=0.0) or []:
            if ent.get("id") is not None and ent.get("name"):
                id_to_name[int(ent["id"])] = ent["name"]
    except Exception:
        return set()

    if not id_to_name:
        return set()

    try:
        shared_ids = store.find_shared_entities(mem_id, list(id_to_name.keys()))
    except AttributeError:
        # SQLite stores without the JOIN method fall back to legacy scan.
        shared_ids = []
        for eid, ename in id_to_name.items():
            mentioning = store.get_memories_mentioning_entity(ename, limit=50)
            if any(m["id"] == mem_id for m in mentioning):
                shared_ids.append(eid)
    except Exception:
        return set()

    return {id_to_name[eid].lower() for eid in shared_ids}


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


# Module-level slot cache for engram allocation.  Avoids re-fetching all
# 5 000 engram_slots rows on every remember() call — a pure performance
# optimisation with no change in behaviour.  The cache is invalidated
# whenever the store instance changes and kept in sync by applying the
# same excitability update to both the DB and the cached list.
#
# Precedent: sensory_buffer._global_buffer, reranker._flashrank_instance,
# pg_recall._titans all use the same module-level cache pattern.
_slot_cache: list[dict] | None = None
_slot_cache_store_id: int | None = None
_slots_initialised: bool = False


def _get_slot_cache(store: Any, num_slots: int) -> list[dict]:
    """Return the cached slot list, populating it on first access."""
    global _slot_cache, _slot_cache_store_id, _slots_initialised

    store_id = id(store)
    if _slot_cache is not None and _slot_cache_store_id == store_id:
        return _slot_cache

    if not _slots_initialised or _slot_cache_store_id != store_id:
        store.init_engram_slots(num_slots)
        _slots_initialised = True

    _slot_cache = store.get_all_engram_slots()
    _slot_cache_store_id = store_id
    return _slot_cache


def _update_slot_cache(
    slot_index: int,
    new_exc: float,
    activated_at: str,
) -> None:
    """Apply an excitability update to the in-memory cache."""
    if _slot_cache is None:
        return
    for slot in _slot_cache:
        if slot["slot_index"] == slot_index:
            slot["excitability"] = new_exc
            slot["last_activated"] = activated_at
            break


def invalidate_slot_cache() -> None:
    """Force-clear the slot cache (for testing or after bulk operations)."""
    global _slot_cache, _slot_cache_store_id, _slots_initialised
    _slot_cache = None
    _slot_cache_store_id = None
    _slots_initialised = False


def allocate_engram_slot(
    mem_id: int,
    settings: Any,
    store: Any,
) -> dict | None:
    """Allocate an engram slot for competitive memory allocation."""
    try:
        all_slots = _get_slot_cache(store, settings.HOPFIELD_MAX_PATTERNS)
        if not all_slots:
            return None
        best_slot, best_exc = engram.find_best_slot(
            all_slots,
            settings.EXCITABILITY_HALF_LIFE_HOURS,
        )
        store.assign_memory_slot(mem_id, best_slot)
        new_exc = engram.compute_boost(best_exc, settings.EXCITABILITY_BOOST)
        now_iso = store._now_iso()
        store.update_engram_slot(best_slot, new_exc, now_iso)
        _update_slot_cache(best_slot, new_exc, now_iso)
        linked_count = store.count_memories_in_slot(
            best_slot,
            exclude_id=mem_id,
        )
        return {
            "slot_index": best_slot,
            "temporally_linked": linked_count,
        }
    except Exception:
        return None
