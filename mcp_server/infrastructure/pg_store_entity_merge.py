"""Entity-merge mixin for PgMemoryStore.

Collapses one near-duplicate concept entity (the *alias*) into another (the
*survivor*), as planned by ``core.entity_dedup``. This is the mutating half of
the fuzzy-dedup feature: the core engine decides *what* to merge (pure, no I/O);
this method performs the rewire atomically.

Kept in its own mixin so ``pg_store_entities.py`` stays under the 300-line cap.
"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# source: structural — the id-lookup fetches exactly the survivor + alias pair
_MERGE_PAIR_COUNT = 2


class PgEntityMergeMixin(PgStoreHost):
    """Atomic entity collapse on PostgreSQL."""

    def merge_entities(self, survivor_id: int, alias_id: int) -> dict[str, Any]:
        """Collapse ``alias_id`` into ``survivor_id`` in one transaction.

        Rewires every ``memory_entities`` link and ``relationships`` edge from
        the alias to the survivor, drops self-loops the rewire creates, lets the
        survivor absorb the alias's heat/recency (bounded ``GREATEST`` — never a
        naive sum that would break the [0,1] heat invariant), then archives the
        alias as a tombstone (``archived=TRUE, heat=0``) rather than deleting it,
        so the merge stays auditable. All statements commit together or roll back.

        No-op (``merged=False``) when the ids are equal, either entity is
        missing, or either is an ``ast_symbol`` — code-symbol identity is
        structural and must never be fuzzy-merged (graphify #1205; defense in
        depth over the core engine's own exclusion).

        Returns ``{merged, survivor_id, alias_id, memory_links_moved,
        relationships_rewired}``.
        """
        result = {
            "merged": False,
            "survivor_id": survivor_id,
            "alias_id": alias_id,
            "memory_links_moved": 0,
            "relationships_rewired": 0,
        }
        if survivor_id == alias_id:
            return result
        rows = self._execute(
            "SELECT id, origin FROM entities WHERE id = ANY(%s::int[])",
            ([int(survivor_id), int(alias_id)],),
        ).fetchall()
        origins = {r["id"]: r.get("origin", "text_concept") for r in rows}
        if len(origins) != _MERGE_PAIR_COUNT or "ast_symbol" in origins.values():
            return result
        try:
            self._execute(
                "INSERT INTO memory_entities (memory_id, entity_id) "
                "SELECT memory_id, %s FROM memory_entities WHERE entity_id = %s "
                "ON CONFLICT DO NOTHING",
                (survivor_id, alias_id),
            )
            moved = self._execute(
                "DELETE FROM memory_entities WHERE entity_id = %s", (alias_id,)
            ).rowcount
            src = self._execute(
                "UPDATE relationships SET source_entity_id = %s "
                "WHERE source_entity_id = %s",
                (survivor_id, alias_id),
            ).rowcount
            tgt = self._execute(
                "UPDATE relationships SET target_entity_id = %s "
                "WHERE target_entity_id = %s",
                (survivor_id, alias_id),
            ).rowcount
            self._execute(
                "DELETE FROM relationships "
                "WHERE source_entity_id = target_entity_id AND source_entity_id = %s",
                (survivor_id,),
            )
            self._execute(
                "UPDATE entities SET "
                "heat = GREATEST(heat, (SELECT heat FROM entities WHERE id = %s)), "
                "last_accessed = GREATEST("
                "  last_accessed, (SELECT last_accessed FROM entities WHERE id = %s)) "
                "WHERE id = %s",
                (alias_id, alias_id, survivor_id),
            )
            self._execute(
                "UPDATE entities SET archived = TRUE, heat = 0 WHERE id = %s",
                (alias_id,),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        result.update(
            merged=True,
            memory_links_moved=int(moved or 0),
            relationships_rewired=int((src or 0) + (tgt or 0)),
        )
        return result
