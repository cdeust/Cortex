"""Relationship CRUD mixin for SqliteMemoryStore."""

from __future__ import annotations

import sqlite3
from typing import Any


class SqliteRelationshipMixin:
    """Relationship persistence operations on SQLite."""

    _conn: sqlite3.Connection

    def insert_relationship(self, data: dict[str, Any]) -> int:
        cur = self._conn.execute(
            "INSERT INTO relationships "
            "(source_entity_id, target_entity_id, relationship_type, weight, "
            "is_causal, confidence, created_at, last_reinforced) "
            "VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), datetime('now'))",
            (
                data["source_entity_id"],
                data["target_entity_id"],
                data["relationship_type"],
                data.get("weight", 1.0),
                int(data.get("is_causal", False)),
                data.get("confidence", 1.0),
                data.get("created_at"),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def count_relationships(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM relationships"
        ).fetchone()
        return row["c"] if row else 0

    def get_relationships_for_entity(
        self, entity_id: int, direction: str = "both", limit: int = 50
    ) -> list[dict[str, Any]]:
        if direction == "outgoing":
            rows = self._conn.execute(
                "SELECT r.*, e.name AS target_name, e.type AS target_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.target_entity_id "
                "WHERE r.source_entity_id = ? "
                "ORDER BY r.weight DESC LIMIT ?",
                (entity_id, limit),
            ).fetchall()
        elif direction == "incoming":
            rows = self._conn.execute(
                "SELECT r.*, e.name AS source_name, e.type AS source_type "
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
        rows = self._conn.execute(
            "SELECT id, source_entity_id, target_entity_id, "
            "relationship_type, weight, is_causal, confidence "
            "FROM relationships"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_relationship_counts(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT entity_id, COUNT(*) AS cnt FROM ("
            "  SELECT source_entity_id AS entity_id FROM relationships "
            "  UNION ALL "
            "  SELECT target_entity_id AS entity_id FROM relationships"
            ") sub GROUP BY entity_id"
        ).fetchall()
        return {row["entity_id"]: row["cnt"] for row in rows}

    def get_entity_relationship_pairs(self) -> set[tuple[str, str]]:
        rows = self._conn.execute(
            "SELECT e1.name AS source_name, e2.name AS target_name "
            "FROM relationships r "
            "JOIN entities e1 ON r.source_entity_id = e1.id "
            "JOIN entities e2 ON r.target_entity_id = e2.id"
        ).fetchall()
        return {(row["source_name"], row["target_name"]) for row in rows}

    def reinforce_or_create_relationship(
        self,
        source_name: str,
        target_name: str,
        delta_weight: float = 0.1,
        rel_type: str = "co_retrieval",
    ) -> None:
        """Hebbian update: co-activation strengthens edges."""
        src = self._conn.execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (source_name,),
        ).fetchone()
        tgt = self._conn.execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (target_name,),
        ).fetchone()
        if not src or not tgt:
            return
        sid, tid = src["id"], tgt["id"]
        # Try to reinforce existing relationship
        cur = self._conn.execute(
            "UPDATE relationships SET "
            "weight = MIN(2.0, weight + ?), "
            "facilitation = MIN(1.0, facilitation + 0.05), "
            "last_reinforced = datetime('now') "
            "WHERE source_entity_id = ? AND target_entity_id = ? "
            "AND relationship_type = ?",
            (delta_weight, sid, tid, rel_type),
        )
        if not cur.rowcount:
            # Check reverse direction
            cur = self._conn.execute(
                "UPDATE relationships SET "
                "weight = MIN(2.0, weight + ?), "
                "facilitation = MIN(1.0, facilitation + 0.05), "
                "last_reinforced = datetime('now') "
                "WHERE source_entity_id = ? AND target_entity_id = ? "
                "AND relationship_type = ?",
                (delta_weight, tid, sid, rel_type),
            )
        if not cur.rowcount:
            # Create new relationship
            self._conn.execute(
                "INSERT INTO relationships "
                "(source_entity_id, target_entity_id, relationship_type, weight) "
                "VALUES (?, ?, ?, ?)",
                (sid, tid, rel_type, delta_weight),
            )
