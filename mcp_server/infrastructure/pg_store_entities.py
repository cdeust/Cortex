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

    def update_entities_heat_batch(self, updates: list[tuple[int, float]]) -> int:
        """Batch-update entity heat. Single round-trip, single commit.

        Source: issue #13 — mirror of update_memories_heat_batch for the
        entity decay path in consolidate.
        """
        if not updates:
            return 0
        ids = [int(u[0]) for u in updates]
        heats = [float(u[1]) for u in updates]
        self._execute(
            "UPDATE entities AS e SET heat = v.new_heat "
            "FROM (SELECT UNNEST(%s::int[]) AS id, "
            "            UNNEST(%s::real[]) AS new_heat) AS v "
            "WHERE e.id = v.id",
            (ids, heats),
        )
        self._conn.commit()
        return len(updates)

    def archive_entities_batch(self, entity_ids: list[int]) -> int:
        """Set heat=0 on many entities in one statement (pruning orphans)."""
        if not entity_ids:
            return 0
        self._execute(
            "UPDATE entities SET heat = 0 WHERE id = ANY(%s::int[])",
            ([int(e) for e in entity_ids],),
        )
        self._conn.commit()
        return len(entity_ids)

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

    def insert_memory_entity(self, memory_id: int, entity_id: int) -> None:
        """Link a memory to an entity. Idempotent via ON CONFLICT."""
        self._execute(
            "INSERT INTO memory_entities (memory_id, entity_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (memory_id, entity_id),
        )

    def get_entities_for_memory(self, memory_id: int) -> list[dict[str, Any]]:
        """Return all entities linked to a memory via the join table."""
        rows = self._execute(
            "SELECT e.* FROM entities e "
            "JOIN memory_entities me ON me.entity_id = e.id "
            "WHERE me.memory_id = %s ORDER BY e.heat DESC",
            (memory_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_memories_for_entity(self, entity_id: int) -> list[dict[str, Any]]:
        """Return all memories linked to an entity via the join table."""
        rows = self._execute(
            "SELECT m.* FROM memories m "
            "JOIN memory_entities me ON me.memory_id = m.id "
            "WHERE me.entity_id = %s ORDER BY m.heat DESC",
            (entity_id,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]
