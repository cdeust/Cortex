"""Relationship CRUD mixin for PgMemoryStore."""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class PgRelationshipMixin(PgStoreHost):
    """Relationship persistence operations on PostgreSQL."""

    def update_relationships_weight_batch(
        self, updates: list[tuple[int, float]]
    ) -> int:
        """Batch-update relationship weights. Single round-trip, single commit.

        source: ADR-0563"""
        if not updates:
            return 0
        ids = [int(u[0]) for u in updates]
        weights = [float(u[1]) for u in updates]
        self._execute(
            "UPDATE relationships AS r SET weight = v.new_weight "
            "FROM (SELECT UNNEST(%s::int[]) AS id, "
            "            UNNEST(%s::real[]) AS new_weight) AS v "
            "WHERE r.id = v.id",
            (ids, weights),
        )
        self._conn.commit()
        return len(updates)

    def delete_relationships_batch(self, rel_ids: list[int]) -> int:
        """Batch-delete relationships by id. Single round-trip.

        source: ADR-0563"""
        if not rel_ids:
            return 0
        self._execute(
            "DELETE FROM relationships WHERE id = ANY(%s::int[])",
            ([int(r) for r in rel_ids],),
        )
        self._conn.commit()
        return len(rel_ids)

    def insert_relationship(self, data: dict[str, Any]) -> int:
        # source: ADR-0563
        row = self._execute(
            "INSERT INTO relationships "
            "(source_entity_id, target_entity_id, relationship_type, weight, "
            "is_causal, confidence, created_at, last_reinforced) "
            "VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s, NOW()), NOW()) "
            "ON CONFLICT (source_entity_id, target_entity_id, relationship_type) "
            "DO UPDATE SET "
            "  weight = GREATEST(relationships.weight, EXCLUDED.weight), "
            "  confidence = GREATEST(relationships.confidence, EXCLUDED.confidence), "
            "  last_reinforced = NOW() "
            "RETURNING id",
            (
                data["source_entity_id"],
                data["target_entity_id"],
                data["relationship_type"],
                data.get("weight", 1.0),
                data.get("is_causal", False),
                data.get("confidence", 1.0),
                data.get("created_at"),
            ),
        ).one()
        self._conn.commit()
        return row["id"]

    def count_relationships(self) -> int:
        row = self._execute("SELECT COUNT(*) AS c FROM relationships").fetchone()
        return row["c"] if row else 0

    def get_relationships_for_entity(
        self, entity_id: int, direction: str = "both", limit: int = 50
    ) -> list[dict[str, Any]]:
        if direction == "outgoing":
            rows = self._execute(
                "SELECT r.*, e.name AS target_name, e.type AS target_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.target_entity_id "
                "WHERE r.source_entity_id = %s "
                "ORDER BY r.weight DESC LIMIT %s",
                (entity_id, limit),
            ).fetchall()
        elif direction == "incoming":
            rows = self._execute(
                "SELECT r.*, e.name AS source_name, e.type AS source_type "
                "FROM relationships r "
                "JOIN entities e ON e.id = r.source_entity_id "
                "WHERE r.target_entity_id = %s "
                "ORDER BY r.weight DESC LIMIT %s",
                (entity_id, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT r.* FROM relationships r "
                "WHERE r.source_entity_id = %s OR r.target_entity_id = %s "
                "ORDER BY r.weight DESC LIMIT %s",
                (entity_id, entity_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_relationships(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT id, source_entity_id, target_entity_id, "
            "relationship_type, weight, is_causal, confidence, "
            "release_probability, facilitation, depression, last_reinforced "
            "FROM relationships"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_relationship_counts(self) -> dict[int, int]:
        rows = self._execute(
            "SELECT entity_id, COUNT(*) AS cnt FROM ("
            "  SELECT source_entity_id AS entity_id FROM relationships "
            "  UNION ALL "
            "  SELECT target_entity_id AS entity_id FROM relationships"
            ") sub GROUP BY entity_id"
        ).fetchall()
        return {row["entity_id"]: row["cnt"] for row in rows}

    def get_entity_relationship_pairs(self) -> set[tuple[str, str]]:
        rows = self._execute(
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
        """Dragon Hatchling Hebbian update via single UPSERT.

        source: ADR-0563"""
        src = self._execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            (source_name,),
        ).fetchone()
        tgt = self._execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(%s) LIMIT 1",
            (target_name,),
        ).fetchone()
        if not src or not tgt:
            return
        sid, tid = int(src["id"]), int(tgt["id"])
        # source: ADR-0563
        self._execute(
            "UPDATE entities SET last_accessed = NOW(), "
            "heat = LEAST(1.0, heat + 0.05) "
            "WHERE id IN (%s, %s)",
            (sid, tid),
        )

        if rel_type == "co_retrieval":
            a, b = (sid, tid) if sid <= tid else (tid, sid)
            self._execute(
                "INSERT INTO relationships "
                "(source_entity_id, target_entity_id, relationship_type, "
                " weight, facilitation, last_reinforced) "
                "VALUES (%s, %s, %s, %s, %s, NOW()) "
                "ON CONFLICT (source_entity_id, target_entity_id, relationship_type) "
                "WHERE relationship_type = 'co_retrieval' "
                "DO UPDATE SET "
                "  weight = LEAST(2.0, relationships.weight + EXCLUDED.weight), "
                "  facilitation = LEAST(1.0, relationships.facilitation + 0.05), "
                "  last_reinforced = NOW()",
                (a, b, rel_type, delta_weight, 0.05),
            )
            return

        # Non-symmetric types — preserve directional semantics.
        updated = self._execute(
            "UPDATE relationships SET "
            "weight = LEAST(2.0, weight + %s), "
            "facilitation = LEAST(1.0, facilitation + 0.05), "
            "last_reinforced = NOW() "
            "WHERE source_entity_id = %s AND target_entity_id = %s "
            "AND relationship_type = %s",
            (delta_weight, sid, tid, rel_type),
        ).rowcount
        if not updated:
            self._execute(
                "INSERT INTO relationships "
                "(source_entity_id, target_entity_id, relationship_type, weight) "
                "VALUES (%s, %s, %s, %s)",
                (sid, tid, rel_type, delta_weight),
            )
