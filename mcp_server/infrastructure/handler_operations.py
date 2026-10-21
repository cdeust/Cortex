"""Statements that lived inside handler modules, as store operations.

Moved unchanged (SQL and semantics) from ``handlers/codebase_analyze.py``,
``codebase_analyze_helpers.py``, ``get_rules.py``, ``anchor.py``,
``remember_helpers.py`` and ``backfill_helpers.py`` so that no handler holds
a connection or writes SQL (ADR-1112 increment 2). Where a handler looped
"select rows, then update each" on one connection, the loop moved here whole,
so one operation is one round trip.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import json
from typing import Any

from mcp_server.infrastructure.store_operations import store_operation


def _tags(raw: object) -> list:
    """Tags from a list (PostgreSQL jsonb) or a JSON string (SQLite)."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return []
    return []


@store_operation
def live_memory_tags_for_agent(conn: Any, agent_context: str) -> list[dict]:
    """(id, tags) of every non-stale memory written under ``agent_context``."""
    rows = conn.execute(
        "SELECT id, tags FROM memories WHERE agent_context = %s AND NOT is_stale",
        (agent_context,),
    ).fetchall()
    return [{"id": row["id"], "tags": _tags(row["tags"])} for row in rows]


@store_operation
def mark_memories_stale(conn: Any, memory_ids: list[int]) -> int:
    """Mark each memory stale; returns how many ids were given (as before)."""
    for mid in memory_ids:
        conn.execute("UPDATE memories SET is_stale = TRUE WHERE id = %s", (mid,))
    return len(memory_ids)


@store_operation
def tag_codebase_memories_mentioning(conn: Any, file_path: str, tag: str) -> int:
    """Add ``tag`` to every live codebase memory whose content mentions
    ``file_path``; returns how many were changed."""
    rows = conn.execute(
        "SELECT id, tags FROM memories "
        "WHERE agent_context = 'codebase' AND NOT is_stale "
        "AND content LIKE %s",
        (f"%{file_path}%",),
    ).fetchall()
    changed = 0
    for row in rows:
        tags = _tags(row["tags"])
        if tag not in tags:
            tags.append(tag)
            conn.execute(
                "UPDATE memories SET tags = %s WHERE id = %s",
                (json.dumps(tags), row["id"]),
            )
            changed += 1
    return changed


@store_operation
def promote_to_semantic(conn: Any, memory_id: int) -> None:
    """Semantic store type, boosted heat and importance (codebase_analyze)."""
    conn.execute(
        "UPDATE memories SET store_type = 'semantic', "
        "heat_base = 0.7, heat_base_set_at = NOW(), "
        "importance = 0.5 WHERE id = %s",
        (memory_id,),
    )


@store_operation
def all_rules_including_inactive(conn: Any) -> list[dict]:
    """Every rule, active or not, by scope then priority."""
    rows = conn.execute(
        "SELECT * FROM memory_rules ORDER BY scope, priority DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@store_operation
def anchor_memory(
    conn: Any, memory_id: int, tags_json: str, content: str, is_global: bool
) -> None:
    """Pin a memory: full heat, no decay, protected, top importance (ADR-0330)."""
    conn.execute(
        "UPDATE memories SET heat_base = 1.0, heat_base_set_at = NOW(), "
        "no_decay = TRUE, is_protected = TRUE, importance = 1.0, "
        "tags = %s::jsonb, content = %s, is_global = %s WHERE id = %s",
        (tags_json, content, is_global, memory_id),
    )


@store_operation
def replica_memory_for_vpath(conn: Any, vpath_json: str) -> int | None:
    """The id of the memory-replica carrying this ``vpath:`` tag, if any."""
    rows = conn.execute(
        "SELECT id FROM memories "
        "WHERE tags @> %s::jsonb "
        "AND tags @> '[\"memory-replica\"]'::jsonb "
        "LIMIT 1",
        (vpath_json,),
    ).fetchall()
    return rows[0]["id"] if rows else None


@store_operation
def refresh_replica_memory(
    conn: Any,
    memory_id: int,
    content: str,
    embedding: bytes | None,
    tags_json: str,
    source: str,
) -> None:
    """Refresh a replica's content, embedding, tags and source; heat and
    protection are preserved."""
    if embedding is not None:
        conn.execute(
            "UPDATE memories "
            "SET content = %s, embedding = %s::vector, "
            "    tags = %s::jsonb, source = %s, "
            "    last_accessed = NOW() "
            "WHERE id = %s",
            (content, embedding, tags_json, source, memory_id),
        )
    else:
        conn.execute(
            "UPDATE memories "
            "SET content = %s, "
            "    tags = %s::jsonb, source = %s, "
            "    last_accessed = NOW() "
            "WHERE id = %s",
            (content, tags_json, source, memory_id),
        )


@store_operation
def backfill_log_hash(conn: Any, file_path: str) -> str | None:
    """The content hash recorded for a backfilled file, if any."""
    row = conn.execute(
        "SELECT file_hash FROM backfill_log WHERE file_path = %s",
        (file_path,),
    ).fetchone()
    return None if row is None else row["file_hash"]


@store_operation
def record_backfill(conn: Any, file_path: str, file_hash: str, count: int) -> None:
    """Record (or refresh) a backfilled file and how many memories it gave."""
    conn.execute(
        "INSERT INTO backfill_log "
        "(file_path, file_hash, memories_imported, processed_at) "
        "VALUES (%s, %s, %s, NOW()) "
        "ON CONFLICT(file_path) DO UPDATE SET "
        "file_hash = EXCLUDED.file_hash, "
        "memories_imported = EXCLUDED.memories_imported, "
        "processed_at = NOW()",
        (file_path, file_hash, count),
    )
