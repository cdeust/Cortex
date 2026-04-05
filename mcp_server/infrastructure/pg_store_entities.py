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
        row = self._execute(
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
        row = self._execute(
            "SELECT * FROM entities WHERE name = %s", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_entity_by_id(self, entity_id: int) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM entities WHERE id = %s", (entity_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_all_entities(
        self, min_heat: float = 0.05, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        if include_archived:
            rows = self._execute(
                "SELECT * FROM entities WHERE heat >= %s", (min_heat,)
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM entities WHERE heat >= %s AND NOT archived",
                (min_heat,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_entities(self) -> int:
        row = self._execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        return row["c"] if row else 0

    def get_entities_of_type(self, entity_type: str) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM entities WHERE type = %s", (entity_type,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_domain_entity_counts(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT domain, COUNT(*) AS count FROM entities "
            "WHERE NOT archived GROUP BY domain ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_isolated_entities(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._execute(
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
        rows = self._execute(
            "SELECT DISTINCT source_entity_id FROM relationships "
            "WHERE relationship_type = 'resolved_by'"
        ).fetchall()
        return {row["source_entity_id"] for row in rows}

    def get_memories_mentioning_entity(
        self, entity_name: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories "
            "WHERE content_tsv @@ phraseto_tsquery('english', %s) "
            "ORDER BY heat DESC LIMIT %s",
            (entity_name, limit),
        ).fetchall()
        if not rows:
            rows = self._execute(
                "SELECT * FROM memories WHERE content ILIKE %s "
                "AND NOT is_stale ORDER BY heat DESC LIMIT %s",
                (
                    "%{}%".format(
                        entity_name.replace("\\", "\\\\")
                        .replace("%", "\\%")
                        .replace("_", "\\_")
                    ),
                    limit,
                ),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]
