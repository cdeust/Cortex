"""Relationship CRUD mixin for PgMemoryStore."""

from __future__ import annotations

from typing import Any

import psycopg


class PgRelationshipMixin:
    """Relationship persistence operations on PostgreSQL."""

    _conn: psycopg.Connection

    def insert_relationship(self, data: dict[str, Any]) -> int:
        row = self._conn.execute(
            "INSERT INTO relationships "
            "(source_entity_id, target_entity_id, relationship_type, weight, "
            "is_causal, confidence, created_at, last_reinforced) "
            "VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()), NOW()) RETURNING id",
            (
                data["source_entity_id"],
                data["target_entity_id"],
                data["relationship_type"],
                data.get("weight", 1.0),
                data.get("is_causal", False),
                data.get("confidence", 1.0),
                data.get("created_at"),
            ),
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def count_relationships(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM relationships").fetchone()
        return row["c"] if row else 0

    def get_relationships_for_entity(
        self, entity_id: int, direction: str = "both", limit: int = 50
    ) -> list[dict[str, Any]]:
        if direction == "outgoing":
            rows = self._conn.execute(
                "SELECT r.*, e.name AS target_name, e.type AS target_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.target_entity_id "
                "WHERE r.source_entity_id = %s "
                "ORDER BY r.weight DESC LIMIT %s",
                (entity_id, limit),
            ).fetchall()
        elif direction == "incoming":
            rows = self._conn.execute(
                "SELECT r.*, e.name AS source_name, e.type AS source_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.source_entity_id "
                "WHERE r.target_entity_id = %s "
                "ORDER BY r.weight DESC LIMIT %s",
                (entity_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT r.* FROM relationships r "
                "WHERE r.source_entity_id = %s OR r.target_entity_id = %s "
                "ORDER BY r.weight DESC LIMIT %s",
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
