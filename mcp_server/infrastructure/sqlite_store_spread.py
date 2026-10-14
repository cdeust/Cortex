"""Client-side spread activation for SqliteMemoryStore.

Query terms -> seed entities -> activation over relationships -> memories
naming the activated entities. The SQLite twin of the PL/pgSQL
``spread_activation_memories()``; moved out of ``sqlite_store_search.py``
to keep that file from growing (ADR-1106).

source: ADR-0616
source: ADR-1106
"""

from __future__ import annotations

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


class SqliteSpreadActivationMixin:
    """Spread activation on SQLite: entities to memories, client side."""

    _conn: PsycopgCompatConnection

    def spread_activation_memories(
        self,
        query_terms: list[str],
        decay: float = 0.65,
        threshold: float = 0.1,
        max_depth: int = 3,
        max_results: int = 50,
        min_heat: float = 0.05,
        domain: str | None = None,
        include_globals: bool = True,
    ) -> list[tuple[int, float]]:
        """Client-side spread activation: query terms -> entities -> memories.

        source: ADR-0616"""
        seed_entities = self._resolve_seed_entities(query_terms, min_heat)
        if not seed_entities:
            return []
        activated = self._propagate_activation(
            seed_entities, decay, threshold, max_depth
        )
        return self._map_entities_to_memories(
            activated, min_heat, max_results, domain, include_globals
        )

    def _resolve_seed_entities(
        self, query_terms: list[str], min_heat: float
    ) -> dict[int, float]:
        seeds: dict[int, float] = {}
        for term in query_terms:
            rows = self._conn.execute(
                "SELECT id FROM entities "
                "WHERE LOWER(name) = LOWER(?) AND heat >= ? AND NOT archived",
                (term, min_heat),
            ).fetchall()
            for r in rows:
                seeds[r["id"]] = 1.0
        return seeds

    def _propagate_activation(
        self,
        seeds: dict[int, float],
        decay: float,
        threshold: float,
        max_depth: int,
    ) -> dict[int, float]:
        activated = dict(seeds)
        frontier = dict(seeds)
        for _ in range(max_depth):
            next_frontier: dict[int, float] = {}
            for eid, act in frontier.items():
                rels = self._conn.execute(
                    "SELECT source_entity_id, target_entity_id, weight, confidence "
                    "FROM relationships "
                    "WHERE source_entity_id = ? OR target_entity_id = ?",
                    (eid, eid),
                ).fetchall()
                for r in rels:
                    neighbor = (
                        r["target_entity_id"]
                        if r["source_entity_id"] == eid
                        else r["source_entity_id"]
                    )
                    new_act = act * decay * r["weight"] * r["confidence"]
                    if new_act >= threshold:
                        if neighbor not in activated or new_act > activated[neighbor]:
                            activated[neighbor] = new_act
                            next_frontier[neighbor] = new_act
            frontier = next_frontier
            if not frontier:
                break
        return activated

    def _entity_memory_rows(self, entity_id: int, min_heat: float) -> list:
        """Memories naming a live entity, the newest 20 when more match.

        source: ADR-1106"""
        entity = self._conn.execute(
            "SELECT name FROM entities WHERE id = ? AND heat >= ? AND NOT archived",
            (entity_id, min_heat),
        ).fetchone()
        if not entity:
            return []
        return self._conn.execute(
            "SELECT id, domain, is_global, created_at FROM current_memories "
            "WHERE content LIKE ? AND heat_base >= ? AND NOT is_stale "
            "ORDER BY created_at DESC, id DESC LIMIT 20",
            (f"%{entity['name']}%", min_heat),
        ).fetchall()

    def _map_entities_to_memories(
        self,
        activated: dict[int, float],
        min_heat: float,
        max_results: int,
        domain: str | None = None,
        include_globals: bool = True,
    ) -> list[tuple[int, float]]:
        """Precondition: none. Postcondition: every returned memory_id either
                belongs to ``domain`` or, when ``include_globals`` is True, carries
                ``is_global = 1`` -- unless ``domain`` is None, in which case no
                filter is applied (mirrors the PL/pgSQL p_domain IS NULL branch).

        source: ADR-0616"""
        memory_acts: dict[int, float] = {}
        created: dict[int, str] = {}
        for eid, act in activated.items():
            for mr in self._entity_memory_rows(eid, min_heat):
                if domain is not None:
                    same_domain = mr["domain"] == domain
                    is_global_row = include_globals and bool(mr["is_global"])
                    if not (same_domain or is_global_row):
                        continue
                mid = mr["id"]
                created[mid] = mr["created_at"]
                if mid not in memory_acts or act > memory_acts[mid]:
                    memory_acts[mid] = act
        # source: ADR-1106 -- exact ties go to the newer memory.
        ranked = sorted(
            memory_acts, key=lambda m: (memory_acts[m], created[m], m), reverse=True
        )
        return [(mid, memory_acts[mid]) for mid in ranked[:max_results]]
