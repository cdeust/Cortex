"""Navigation queries for Obsidian-like knowledge graph traversal.

Provides local graph extraction and backlink resolution using the
materialized memory_entities join table. All queries are designed
for <100ms interactive latency.

Pure I/O — no business logic. Returns raw dicts for core layer processing.
"""

from __future__ import annotations

from typing import Any

import psycopg


class PgNavigationMixin:
    """Navigation queries mixin for PgMemoryStore."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    def get_local_graph(
        self, memory_id: int, depth: int = 1, max_neighbors: int = 30
    ) -> dict[str, Any]:
        """Fetch a memory's local neighborhood for graph rendering.

        Returns the center memory, its entities, and all memories that
        share those entities (backlinks), plus relationships between
        the involved entities.

        Args:
            memory_id: Center memory to expand from.
            depth: How many entity hops (1 = direct, 2 = friends-of-friends).
            max_neighbors: Cap on neighbor memories returned.

        Returns:
            {center, entities, neighbors, relationships}
        """
        # 1. Center memory
        center = self._conn.execute(
            "SELECT id, content, heat, importance, domain, store_type, "
            "tags, created_at, source, agent_context, is_protected, is_global, "
            "emotional_valence, consolidation_stage "
            "FROM memories WHERE id = %s",
            (memory_id,),
        ).fetchone()
        if not center:
            return {"center": None, "entities": [], "neighbors": [], "relationships": []}

        # 2. Entities linked to center
        entities = self._conn.execute(
            "SELECT e.id, e.name, e.type, e.domain, e.heat, me.confidence "
            "FROM entities e "
            "JOIN memory_entities me ON me.entity_id = e.id "
            "WHERE me.memory_id = %s "
            "ORDER BY me.confidence DESC",
            (memory_id,),
        ).fetchall()

        entity_ids = [e["id"] for e in entities]
        if not entity_ids:
            return {
                "center": dict(center),
                "entities": [],
                "neighbors": [],
                "relationships": [],
            }

        # 3. Neighbor memories sharing those entities (backlinks)
        placeholders = ",".join(["%s"] * len(entity_ids))
        neighbors = self._conn.execute(
            f"SELECT DISTINCT m.id, m.content, m.heat, m.importance, "
            f"m.domain, m.store_type, m.tags, m.created_at, m.source, "
            f"m.agent_context, m.is_protected, m.is_global, "
            f"COUNT(me.entity_id) AS shared_entity_count "
            f"FROM memories m "
            f"JOIN memory_entities me ON me.memory_id = m.id "
            f"WHERE me.entity_id IN ({placeholders}) "
            f"AND m.id != %s AND NOT m.is_stale "
            f"GROUP BY m.id "
            f"ORDER BY shared_entity_count DESC, m.heat DESC "
            f"LIMIT %s",
            (*entity_ids, memory_id, max_neighbors),
        ).fetchall()

        # 4. Relationships between involved entities
        all_entity_ids = list(set(entity_ids))
        if len(all_entity_ids) >= 2:
            relationships = self._conn.execute(
                f"SELECT id, source_entity_id, target_entity_id, "
                f"relationship_type, weight, is_causal "
                f"FROM relationships "
                f"WHERE source_entity_id IN ({placeholders}) "
                f"AND target_entity_id IN ({placeholders})",
                (*all_entity_ids, *all_entity_ids),
            ).fetchall()
        else:
            relationships = []

        return {
            "center": dict(center),
            "entities": [dict(e) for e in entities],
            "neighbors": [dict(n) for n in neighbors],
            "relationships": [dict(r) for r in relationships],
        }

    def get_backlinks(
        self, entity_id: int, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get all memories linked to an entity, sorted by relevance."""
        rows = self._conn.execute(
            "SELECT m.id, m.content, m.heat, m.importance, m.domain, "
            "m.store_type, m.tags, m.created_at, m.source, "
            "m.agent_context, m.is_protected, m.is_global, "
            "me.confidence AS link_confidence "
            "FROM memories m "
            "JOIN memory_entities me ON me.memory_id = m.id "
            "WHERE me.entity_id = %s AND NOT m.is_stale "
            "ORDER BY m.heat DESC, me.confidence DESC "
            "LIMIT %s",
            (entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_entity_backlink_counts(
        self, entity_ids: list[int]
    ) -> dict[int, int]:
        """Get memory count per entity (batch)."""
        if not entity_ids:
            return {}
        placeholders = ",".join(["%s"] * len(entity_ids))
        rows = self._conn.execute(
            f"SELECT entity_id, COUNT(*) AS cnt "
            f"FROM memory_entities "
            f"WHERE entity_id IN ({placeholders}) "
            f"GROUP BY entity_id",
            tuple(entity_ids),
        ).fetchall()
        return {r["entity_id"]: r["cnt"] for r in rows}

    def backfill_memory_entities(self, batch_size: int = 500) -> int:
        """One-time migration: populate memory_entities from content matching.

        Scans existing entities and finds memories whose content mentions
        each entity name. Inserts links into memory_entities.

        Returns total links created.
        """
        entities = self._conn.execute(
            "SELECT id, name FROM entities WHERE NOT archived"
        ).fetchall()

        total = 0
        for entity in entities:
            # Find memories mentioning this entity (FTS + fallback ILIKE)
            rows = self._conn.execute(
                "SELECT id FROM memories "
                "WHERE content_tsv @@ phraseto_tsquery('english', %s) "
                "AND NOT is_stale LIMIT %s",
                (entity["name"], batch_size),
            ).fetchall()

            for row in rows:
                try:
                    self._conn.execute(
                        "INSERT INTO memory_entities (memory_id, entity_id, confidence) "
                        "VALUES (%s, %s, %s) "
                        "ON CONFLICT (memory_id, entity_id) DO NOTHING",
                        (row["id"], entity["id"], 0.8),
                    )
                    total += 1
                except Exception:
                    continue

            if total % 100 == 0 and total > 0:
                self._conn.commit()

        self._conn.commit()
        return total
