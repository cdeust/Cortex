"""Entity CRUD mixin for SqliteMemoryStore."""

from __future__ import annotations

import sqlite3
from typing import Any


class SqliteEntityMixin:
    """Entity persistence operations on SQLite."""

    _conn: sqlite3.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by SqliteMemoryStore."""
        return dict(row)

    def insert_entity(self, data: dict[str, Any]) -> int:
        cur = self._conn.execute(
            "INSERT INTO entities (name, type, domain, created_at, last_accessed, heat) "
            "VALUES (?, ?, ?, COALESCE(?, datetime('now')), datetime('now'), ?)",
            (
                data["name"],
                data["type"],
                data.get("domain", ""),
                data.get("created_at"),
                data.get("heat", 1.0),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_entity_by_name(self, name: str) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM entities WHERE name = ?", (name,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_entity_by_id(self, entity_id: int) -> dict[str, Any] | None:
        cur = self._conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
        row = cur.fetchone()
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
                "SELECT * FROM entities WHERE heat >= ? AND NOT archived",
                (min_heat,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_entities(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        return row["c"] if row else 0

    def get_entities_of_type(self, entity_type: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE type = ?", (entity_type,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_domain_entity_counts(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT domain, COUNT(*) AS count FROM entities "
            "WHERE NOT archived GROUP BY domain ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_isolated_entities(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """SELECT e.*, COALESCE(r.rel_count, 0) AS relationship_count
            FROM entities e
            LEFT JOIN (
                SELECT source_entity_id AS eid, COUNT(*) AS rel_count
                FROM relationships GROUP BY source_entity_id
            ) r ON r.eid = e.id
            WHERE NOT e.archived
            ORDER BY relationship_count ASC, e.heat DESC
            LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_resolved_entity_ids(self) -> set[int]:
        rows = self._conn.execute(
            "SELECT DISTINCT source_entity_id FROM relationships "
            "WHERE relationship_type = 'resolved_by'"
        ).fetchall()
        return {row["source_entity_id"] for row in rows}

    def insert_memory_entity(self, memory_id: int, entity_id: int) -> None:
        """Link a memory to an entity. Idempotent via PRIMARY KEY."""
        self._conn.execute(
            "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id) "
            "VALUES (?, ?)",
            (memory_id, entity_id),
        )
        self._conn.commit()

    def get_entities_for_memory(self, memory_id: int) -> list[dict[str, Any]]:
        """Return all entities linked to a memory via the join table."""
        rows = self._conn.execute(
            "SELECT e.* FROM entities e "
            "JOIN memory_entities me ON me.entity_id = e.id "
            "WHERE me.memory_id = ? ORDER BY e.heat DESC",
            (memory_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_memories_for_entity(self, entity_id: int) -> list[dict[str, Any]]:
        """Return all memories linked to an entity via the join table."""
        rows = self._conn.execute(
            "SELECT m.* FROM memories m "
            "JOIN memory_entities me ON me.memory_id = m.id "
            "WHERE me.entity_id = ? ORDER BY m.heat DESC",
            (entity_id,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_mentioning_entity(
        self, entity_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        # Try FTS5 first
        rows = self._conn.execute(
            "SELECT m.* FROM memories m "
            "JOIN memories_fts f ON f.rowid = m.id "
            "WHERE memories_fts MATCH ? "
            "ORDER BY m.heat DESC LIMIT ?",
            (entity_name, limit),
        ).fetchall()
        if not rows:
            # Fallback to LIKE
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE content LIKE ? "
                "AND NOT is_stale ORDER BY heat DESC LIMIT ?",
                (f"%{entity_name}%", limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]
