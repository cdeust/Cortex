"""Prospective-memory (trigger-based recall) mixin for PgMemoryStore.

Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — trigger-based proactive recall is its own
concern, distinct from procedural skills/archives/engrams.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgProspectiveMixin(PgStoreHost):
    """Prospective (trigger-based) memory CRUD on PostgreSQL."""

    def insert_prospective_memory(self, data: dict[str, Any]) -> int:
        row = self._execute(
            "INSERT INTO prospective_memories "
            "(content, trigger_condition, trigger_type, "
            "target_directory, is_active, triggered_count, created_by, "
            "source_memory_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                data["content"],
                data["trigger_condition"],
                data["trigger_type"],
                data.get("target_directory"),
                data.get("is_active", True),
                data.get("triggered_count", 0),
                data.get("created_by", ""),
                data.get("source_memory_id"),
            ),
        ).one()
        self._conn.commit()
        return row["id"]

    def get_active_prospective_memories(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM prospective_memories WHERE is_active"
        ).fetchall()
        return [dict(r) for r in rows]

    def trigger_prospective_memory(self, pm_id: int) -> None:
        self._execute(
            "UPDATE prospective_memories SET triggered_at = NOW(), "
            "triggered_count = triggered_count + 1 WHERE id = %s",
            (pm_id,),
        )
        self._conn.commit()

    def deactivate_prospective_memory(self, pm_id: int) -> None:
        self._execute(
            "UPDATE prospective_memories SET is_active = FALSE WHERE id = %s",
            (pm_id,),
        )
        self._conn.commit()
