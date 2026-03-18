"""Decay cycle — periodic heat decay for all memories and entities.

Applies thermodynamic cooling to all active memories based on elapsed
time since last access. High-importance and emotional memories resist
decay. Protected memories are never decayed.

Pure business logic — receives memory data, returns updated heat values.
Storage operations are handled by the caller.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp_server.core.thermodynamics import compute_decay


def _hours_since_access(mem: dict, now: datetime) -> float | None:
    """Return hours elapsed since last access, or None if unparseable."""
    last_accessed = mem.get("last_accessed", mem.get("created_at", ""))
    if not last_accessed:
        return None
    try:
        last_dt = datetime.fromisoformat(last_accessed)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        hours = (now - last_dt).total_seconds() / 3600.0
        return hours if hours > 0 else None
    except (ValueError, TypeError):
        return None


def _compute_single_decay(
    mem: dict,
    now: datetime,
    decay_factor: float,
    importance_decay_factor: float,
    emotional_decay_resistance: float,
) -> tuple[int, float] | None:
    """Compute decay for a single memory. Returns (id, new_heat) or None."""
    current_heat = mem.get("heat", 0.0)
    hours = _hours_since_access(mem, now)
    if hours is None:
        return None

    new_heat = compute_decay(
        current_heat,
        hours,
        importance=mem.get("importance", 0.5),
        valence=mem.get("emotional_valence", 0.0),
        confidence=mem.get("confidence", 1.0),
        decay_factor=decay_factor,
        importance_decay_factor=importance_decay_factor,
        emotional_decay_resistance=emotional_decay_resistance,
    )

    if abs(new_heat - current_heat) > 0.001:
        return (mem["id"], round(new_heat, 6))
    return None


def compute_decay_updates(
    memories: list[dict],
    now: datetime | None = None,
    *,
    decay_factor: float = 0.95,
    importance_decay_factor: float = 0.998,
    emotional_decay_resistance: float = 0.5,
    cold_threshold: float = 0.05,
) -> list[tuple[int, float]]:
    """Compute new heat values for all memories.

    Returns list of (memory_id, new_heat) tuples for memories that changed.
    Skips protected memories and already-cold memories.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    updates: list[tuple[int, float]] = []
    for mem in memories:
        if mem.get("is_protected") or mem.get("heat", 0.0) < cold_threshold:
            continue
        result = _compute_single_decay(
            mem,
            now,
            decay_factor,
            importance_decay_factor,
            emotional_decay_resistance,
        )
        if result is not None:
            updates.append(result)

    return updates


def _parse_hours_since_access(record: dict, now: datetime) -> float | None:
    """Parse hours since last access from a memory or entity record."""
    last_accessed = record.get("last_accessed", record.get("created_at", ""))
    if not last_accessed:
        return None
    try:
        last_dt = datetime.fromisoformat(last_accessed)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        hours = (now - last_dt).total_seconds() / 3600.0
        return hours if hours > 0 else None
    except (ValueError, TypeError):
        return None


def compute_entity_decay(
    entities: list[dict],
    now: datetime | None = None,
    *,
    decay_factor: float = 0.98,
    cold_threshold: float = 0.05,
) -> list[tuple[int, float]]:
    """Compute new heat values for entities.

    Entities decay slower than memories (0.98 vs 0.95).
    Returns list of (entity_id, new_heat) tuples.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    updates: list[tuple[int, float]] = []
    for entity in entities:
        current_heat = entity.get("heat", 0.0)
        if current_heat < cold_threshold:
            continue
        hours = _parse_hours_since_access(entity, now)
        if hours is None:
            continue
        new_heat = current_heat * (decay_factor**hours)
        if abs(new_heat - current_heat) > 0.001:
            updates.append((entity["id"], round(new_heat, 6)))

    return updates
