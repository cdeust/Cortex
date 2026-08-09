"""Entity co-access / shared-entity JOIN-query mixin for PgMemoryStore.

Split out of pg_store_queries.py (issue #407: 401 lines over the
300-line §4.1 cap) — Phase 2 JOIN-based replacements for what used to
be Python-side substring scans (plasticity/write_post_store); their
own concern, distinct from the plain filtered-read queries.
"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgCoAccessMixin(PgStoreHost):
    """Entity co-access / shared-entity JOIN queries on PostgreSQL."""

    def find_co_accessed_pairs(self, memory_ids: list[int]) -> list[tuple[int, int]]:
        """Entity pairs that co-occur in any of the sampled memories.

        Replaces the Python O(N_mem × N_ent) substring scan in
        ``plasticity._find_co_accessed_pairs`` with a SQL self-join on
        ``memory_entities``. Cost: O(pairs) via the composite PK
        (memory_id, entity_id). Returns sorted-tuple form (a < b) to
        match the pre-Phase-2 caller contract.

        Precondition: Phase 0.4.5 backfill complete (I4 coverage ≥ 99%).
        Without it, the JOIN misses pairs the substring scan would find.

        Source: docs/program/phase-5-pool-admission-design.md (Phase 2
        B1 JOIN replacement); docs/invariants/cortex-invariants.md §I4.
        """
        if not memory_ids:
            return []
        rows = self._execute(
            """
            SELECT DISTINCT
                LEAST(me1.entity_id, me2.entity_id) AS a,
                GREATEST(me1.entity_id, me2.entity_id) AS b
            FROM memory_entities me1
            JOIN memory_entities me2
              ON me1.memory_id = me2.memory_id
             AND me1.entity_id < me2.entity_id
            WHERE me1.memory_id = ANY(%s::int[])
            """,
            (memory_ids,),
        ).fetchall()
        return [(int(r["a"]), int(r["b"])) for r in rows]

    def find_shared_entities(self, memory_id: int, entity_ids: list[int]) -> list[int]:
        """Entity IDs from the candidate set that are linked to this memory.

        Replaces the Python substring scan in
        ``write_post_store._find_shared_entities`` with a SQL lookup
        on ``memory_entities``. Used by synaptic tagging (Frey & Morris
        1997) to decide which weak memories share entities with a new
        strong event.

        Precondition: Phase 0.4.5 backfill; I4 coverage ≥ 99%.

        Source: Phase 2 B2 JOIN replacement.
        """
        if not entity_ids:
            return []
        rows = self._execute(
            "SELECT entity_id FROM memory_entities "
            "WHERE memory_id = %s AND entity_id = ANY(%s::int[])",
            (memory_id, entity_ids),
        ).fetchall()
        return [int(r["entity_id"]) for r in rows]
