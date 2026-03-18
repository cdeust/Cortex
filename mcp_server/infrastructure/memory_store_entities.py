"""Entity CRUD and query mixin for MemoryStore."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


class MemoryEntityMixin:
    """Entity persistence operations.

    Requires _conn (sqlite3.Connection) on the host class.
    """

    _conn: sqlite3.Connection

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def insert_entity(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        cursor = self._conn.execute(
            "INSERT INTO entities (name, type, domain, created_at, last_accessed, heat) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                data["name"],
                data["type"],
                data.get("domain", ""),
                data.get("created_at", now),
                now,
                data.get("heat", 1.0),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_entity_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_entity_by_id(self, entity_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_entities(
        self, min_heat: float = 0.05, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        if include_archived:
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE heat >= ?", (min_heat,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE heat >= ? AND archived = 0",
                (min_heat,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_entities(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as c FROM entities").fetchone()
        return row["c"] if row else 0

    def get_entities_of_type(self, entity_type: str) -> list[dict[str, Any]]:
        """Get entities of a specific type."""
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE type = ?", (entity_type,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_domain_entity_counts(self) -> list[dict[str, Any]]:
        """Return entity counts per domain for gap detection."""
        rows = self._conn.execute(
            "SELECT domain, COUNT(*) as count FROM entities "
            "WHERE archived = 0 GROUP BY domain ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_isolated_entities(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return entities that appear in few or no relationships."""
        rows = self._conn.execute(
            """
            SELECT e.*, COALESCE(r.rel_count, 0) as relationship_count
            FROM entities e
            LEFT JOIN (
                SELECT source_entity_id as eid, COUNT(*) as rel_count
                FROM relationships GROUP BY source_entity_id
            ) r ON r.eid = e.id
            WHERE e.archived = 0
            ORDER BY relationship_count ASC, e.heat DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_resolved_entity_ids(self) -> set[int]:
        """Get entity IDs that have a 'resolved_by' relationship."""
        rows = self._conn.execute(
            "SELECT DISTINCT source_entity_id FROM relationships "
            "WHERE relationship_type = 'resolved_by'"
        ).fetchall()
        return {row["source_entity_id"] for row in rows}

    def get_memories_mentioning_entity(
        self, entity_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Find memories whose content mentions an entity name."""
        safe = entity_name.replace('"', '""')
        try:
            rows = self._conn.execute(
                "SELECT m.* FROM memories m "
                "JOIN memories_fts fts ON fts.rowid = m.id "
                "WHERE memories_fts MATCH ? ORDER BY m.heat DESC LIMIT ?",
                (f'"{safe}"', limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except Exception:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE content LIKE ? AND is_stale = 0 "
                "ORDER BY heat DESC LIMIT ?",
                (f"%{entity_name}%", limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
