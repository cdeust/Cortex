"""Dashboard data formatting helpers.

Pure functions that transform store data into dashboard API responses.
No I/O or server logic -- only data formatting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def build_dashboard_data(store) -> dict:
    """Assemble all dashboard data in a single response."""
    counts = store.count_memories()
    hot = store.get_hot_memories(min_heat=0.0, limit=200)
    entities = store.get_all_entities(min_heat=0.0)
    relationships = store.get_all_relationships()
    recent = store.get_recent_memories(limit=50)
    domain_counts = store.get_domain_counts()
    engram_slots = _safe_call(store.get_all_engram_slots, [])
    slot_occupancy = _safe_call(store.get_slot_occupancy, {})

    engram_active = build_engram_data(engram_slots, slot_occupancy)

    stage_counts = _safe_call(store.get_stage_counts, {})
    schema_count = _safe_call(store.count_schemas, 0)

    return {
        "stats": build_stats(
            store,
            counts,
            len(engram_slots),
            len(engram_active),
            stage_counts=stage_counts,
            schema_count=schema_count,
        ),
        "hot_memories": [format_memory(m, 120) for m in hot],
        "entities": [format_entity(e) for e in entities],
        "relationships": [format_relationship(r) for r in relationships],
        "recent_memories": [format_memory(m, 200) for m in recent],
        "engram_slots": engram_active,
        "domain_counts": domain_counts,
        "stage_counts": stage_counts,
        "schema_count": schema_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _safe_call(fn, default):
    """Call a store method, returning default on error."""
    try:
        return fn()
    except Exception:
        return default


def build_stats(
    store,
    counts: dict,
    total_slots: int = 0,
    active_slots: int = 0,
    stage_counts: dict | None = None,
    schema_count: int = 0,
) -> dict:
    """Build the stats summary block."""
    sc = stage_counts or {}
    return {
        "total": counts.get("total", 0),
        "episodic": counts.get("episodic", 0),
        "semantic": counts.get("semantic", 0),
        "active": counts.get("active", 0),
        "archived": counts.get("archived", 0),
        "stale": counts.get("stale", 0),
        "protected": counts.get("protected", 0),
        "avg_heat": round(store.get_avg_heat(), 4),
        "entities": store.count_entities(),
        "relationships": store.count_relationships(),
        "triggers": store.count_active_triggers(),
        "last_consolidation": store.get_last_consolidation(),
        "engram_total_slots": total_slots,
        "engram_occupied_slots": active_slots,
        "labile": sc.get("labile", 0),
        "early_ltp": sc.get("early_ltp", 0),
        "late_ltp": sc.get("late_ltp", 0),
        "consolidated": sc.get("consolidated", 0),
        "reconsolidating": sc.get("reconsolidating", 0),
        "schema_count": schema_count,
    }


def format_memory(m: dict, content_limit: int) -> dict:
    """Format a memory row for the dashboard API."""
    content = m.get("content", "")
    truncated = (
        content[:content_limit] + "..." if len(content) > content_limit else content
    )
    return {
        "id": m["id"],
        "content": truncated,
        "heat": round(m.get("heat", 0), 4),
        "importance": round(m.get("importance", 0.5), 4),
        "store_type": m.get("store_type", "episodic"),
        "tags": parse_tags(m.get("tags", [])),
        "created_at": m.get("created_at", ""),
        "domain": m.get("domain", ""),
        "surprise_score": round(m.get("surprise_score", 0), 4),
        "emotional_valence": round(m.get("emotional_valence", 0), 4),
        "compression_level": m.get("compression_level", 0),
        "is_compressed": bool(m.get("is_compressed", 0)),
        "is_protected": bool(m.get("is_protected", 0)),
        "slot_index": m.get("slot_index"),
        "source": m.get("source", ""),
        "agent_context": m.get("agent_context", ""),
        "access_count": m.get("access_count", 0),
        "consolidation_stage": m.get("consolidation_stage", "labile"),
        "schema_match_score": round(m.get("schema_match_score", 0), 4),
        "interference_score": round(m.get("interference_score", 0), 4),
        "hippocampal_dependency": round(m.get("hippocampal_dependency", 1.0), 4),
        "theta_phase": round(m.get("theta_phase_at_encoding", 0), 4),
    }


def format_entity(e: dict) -> dict:
    """Format an entity row for the dashboard API."""
    return {
        "id": e["id"],
        "name": e.get("name", ""),
        "type": e.get("type", "unknown"),
        "heat": round(e.get("heat", 0), 4),
        "domain": e.get("domain", ""),
    }


def format_relationship(r: dict) -> dict:
    """Format a relationship row for the dashboard API."""
    return {
        "source": r["source_entity_id"],
        "target": r["target_entity_id"],
        "type": r.get("relationship_type", "related"),
        "weight": round(r.get("weight", 1.0), 4),
        "is_causal": bool(r.get("is_causal", 0)),
    }


def build_engram_data(slots: list, occupancy: dict) -> list:
    """Format engram slot data -- only slots with memories assigned."""
    result = []
    for s in slots:
        idx = s.get("slot_index", 0)
        occ = occupancy.get(idx, 0)
        if occ > 0:
            result.append(
                {
                    "slot_index": idx,
                    "excitability": round(s.get("excitability", 0), 4),
                    "last_activated": s.get("last_activated", ""),
                    "occupancy": occ,
                }
            )
    return result


def parse_tags(tags) -> list:
    """Parse tags from various storage formats."""
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        try:
            return json.loads(tags)
        except (ValueError, TypeError):
            return []
    return []
