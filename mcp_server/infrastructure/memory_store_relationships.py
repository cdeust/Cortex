"""Relationship CRUD and query mixin for MemoryStore."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


class MemoryRelationshipMixin:
    """Relationship persistence operations.

    Requires _conn (sqlite3.Connection) on the host class.
    """

    _conn: sqlite3.Connection

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def insert_relationship(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        cursor = self._conn.execute(
            "INSERT INTO relationships "
            "(source_entity_id, target_entity_id, relationship_type, weight, "
            "is_causal, confidence, created_at, last_reinforced) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["source_entity_id"],
                data["target_entity_id"],
                data["relationship_type"],
                data.get("weight", 1.0),
                1 if data.get("is_causal", False) else 0,
                data.get("confidence", 1.0),
                data.get("created_at", now),
                now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def count_relationships(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()
        return row["c"] if row else 0

    def get_relationships_for_entity(
        self, entity_id: int, direction: str = "both", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get relationships involving an entity.

        direction: 'outgoing', 'incoming', or 'both'.
        """
        if direction == "outgoing":
            rows = self._conn.execute(
                "SELECT r.*, e.name as target_name, e.type as target_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.target_entity_id "
                "WHERE r.source_entity_id = ? "
                "ORDER BY r.weight DESC LIMIT ?",
                (entity_id, limit),
            ).fetchall()
        elif direction == "incoming":
            rows = self._conn.execute(
                "SELECT r.*, e.name as source_name, e.type as source_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.source_entity_id "
                "WHERE r.target_entity_id = ? "
                "ORDER BY r.weight DESC LIMIT ?",
                (entity_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT r.* FROM relationships r "
                "WHERE r.source_entity_id = ? OR r.target_entity_id = ? "
                "ORDER BY r.weight DESC LIMIT ?",
                (entity_id, entity_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_relationships(self) -> list[dict[str, Any]]:
        """Get all relationships."""
        rows = self._conn.execute(
            "SELECT id, source_entity_id, target_entity_id, "
            "relationship_type, weight, is_causal, confidence "
            "FROM relationships"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_relationship_counts(self) -> dict[int, int]:
        """Get count of relationships per entity."""
        rows = self._conn.execute(
            "SELECT entity_id, COUNT(*) as cnt FROM ("
            "  SELECT source_entity_id AS entity_id FROM relationships "
            "  UNION ALL "
            "  SELECT target_entity_id AS entity_id FROM relationships"
            ") GROUP BY entity_id"
        ).fetchall()
        return {row["entity_id"]: row["cnt"] for row in rows}

    def get_entity_relationship_pairs(self) -> set[tuple[str, str]]:
        """Get all (source_name, target_name) pairs from relationships."""
        rows = self._conn.execute(
            "SELECT e1.name AS source_name, e2.name AS target_name "
            "FROM relationships r "
            "JOIN entities e1 ON r.source_entity_id = e1.id "
            "JOIN entities e2 ON r.target_entity_id = e2.id"
        ).fetchall()
        return {(row["source_name"], row["target_name"]) for row in rows}
