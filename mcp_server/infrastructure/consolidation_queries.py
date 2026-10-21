"""Consolidation statements that lived inside handler modules, as store
operations (ADR-1112 increment 2).

Moved unchanged from ``handlers/consolidation/memify.py``,
``memify_derive.py``, ``sleep.py`` and ``cascade.py``. A handler no longer
holds a pool connection while it computes (``sleep`` used to hold one across
an ``encode`` per memory): each statement borrows a connection for itself.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.store_operations import store_operation


@store_operation
def relationship_weights(conn: Any) -> list[dict]:
    """(id, source_entity_id, target_entity_id, weight) of every relationship."""
    rows = conn.execute(
        "SELECT id, source_entity_id, target_entity_id, weight FROM relationships",
    ).fetchall()
    return [dict(r) for r in rows]


@store_operation
def strong_relationships(conn: Any, threshold: float, limit: int) -> list[dict]:
    """Relationships with ``weight >= threshold``, heaviest first."""
    rows = conn.execute(
        "SELECT id, source_entity_id, target_entity_id, relationship_type, "
        "weight FROM relationships WHERE weight >= %s "
        "ORDER BY weight DESC LIMIT %s",
        (threshold, limit),
    ).fetchall()
    return [dict(r) for r in rows]


@store_operation
def set_memory_embedding(conn: Any, memory_id: int, embedding: Any) -> None:
    """Replace one memory's embedding (sleep's stale re-embedding)."""
    conn.execute(
        "UPDATE memories SET embedding = %s WHERE id = %s",
        (embedding, memory_id),
    )


@store_operation
def set_stage_entered_at(conn: Any, memory_id: int, entered_at: Any) -> None:
    """Stamp when a memory entered its current consolidation stage."""
    conn.execute(
        "UPDATE memories SET stage_entered_at = %s WHERE id = %s",
        (entered_at, memory_id),
    )
