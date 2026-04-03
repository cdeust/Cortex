"""Entity CRUD mixin for PgMemoryStore."""

from __future__ import annotations

from typing import Any

import psycopg


class PgEntityMixin:
    """Entity persistence operations on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    def insert_entity(self, data: dict[str, Any]) -> int:
        row = self._conn.execute(
            "INSERT INTO entities (name, type, domain, created_at, last_accessed, heat) "
            "VALUES (%s, %s, %s, COALESCE(%s, NOW()), NOW(), %s) RETURNING id",
            (
                data["name"],
                data["type"],
                data.get("domain", ""),
                data.get("created_at"),
                data.get("heat", 1.0),
            ),
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_entity_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE name = %s", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_entity_by_id(self, entity_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = %s", (entity_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_entities(
        self, min_heat: float = 0.05, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        if include_archived:
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE heat >= %s", (min_heat,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM entities WHERE heat >= %s AND NOT archived",
                (min_heat,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_entities(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        return row["c"] if row else 0

    def get_entities_of_type(self, entity_type: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM entities WHERE type = %s", (entity_type,)
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
            LIMIT %s""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_resolved_entity_ids(self) -> set[int]:
        rows = self._conn.execute(
            "SELECT DISTINCT source_entity_id FROM relationships "
            "WHERE relationship_type = 'resolved_by'"
        ).fetchall()
        return {row["source_entity_id"] for row in rows}

    def link_memory_to_entities(
        self, memory_id: int, entity_ids: list[int], confidence: float = 1.0
    ) -> int:
        """Materialize memory↔entity links in the join table.

        Uses ON CONFLICT DO UPDATE to refresh confidence on re-link.
        Returns the number of links inserted/updated.
        """
        if not entity_ids:
            return 0
        count = 0
        for eid in entity_ids:
            try:
                self._conn.execute(
                    "INSERT INTO memory_entities (memory_id, entity_id, confidence) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (memory_id, entity_id) DO UPDATE "
                    "SET confidence = EXCLUDED.confidence",
                    (memory_id, eid, confidence),
                )
                count += 1
            except Exception:
                continue
        self._conn.commit()
        return count

    def get_entities_for_memory(self, memory_id: int) -> list[dict[str, Any]]:
        """Get all entities linked to a memory via the join table."""
        rows = self._conn.execute(
            "SELECT e.*, me.confidence AS link_confidence "
            "FROM entities e "
            "JOIN memory_entities me ON me.entity_id = e.id "
            "WHERE me.memory_id = %s ORDER BY me.confidence DESC",
            (memory_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_memories_for_entity(
        self, entity_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get all memories linked to an entity (backlinks)."""
        rows = self._conn.execute(
            "SELECT m.id, m.content, m.heat, m.importance, m.domain, "
            "m.store_type, m.tags, m.created_at, m.source, m.agent_context, "
            "m.is_protected, m.is_global, me.confidence AS link_confidence "
            "FROM memories m "
            "JOIN memory_entities me ON me.memory_id = m.id "
            "WHERE me.entity_id = %s AND NOT m.is_stale "
            "ORDER BY m.heat DESC LIMIT %s",
            (entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_memories_mentioning_entity(
        self, entity_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories "
            "WHERE content_tsv @@ phraseto_tsquery('english', %s) "
            "ORDER BY heat DESC LIMIT %s",
            (entity_name, limit),
        ).fetchall()
        if not rows:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE content ILIKE %s "
                "AND NOT is_stale ORDER BY heat DESC LIMIT %s",
                (f"%{entity_name}%", limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]
