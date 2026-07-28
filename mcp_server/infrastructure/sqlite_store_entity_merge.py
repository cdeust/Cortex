"""Entity-merge mixin for SqliteMemoryStore — mirror of PgEntityMergeMixin.

SQLite parity for the mutating half of fuzzy entity dedup (``core.entity_dedup``
plans the merge; this performs it atomically). Kept in its own mixin so
``sqlite_store_entities.py`` stays focused.
"""

from __future__ import annotations

from typing import Any
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection

# source: structural — the id-lookup fetches exactly the survivor + alias pair
_MERGE_PAIR_COUNT = 2


class SqliteEntityMergeMixin:
    """Atomic entity collapse on SQLite."""

    _conn: PsycopgCompatConnection

    def merge_entities(self, survivor_id: int, alias_id: int) -> dict[str, Any]:
        """Collapse ``alias_id`` into ``survivor_id`` in one transaction.

        Semantics identical to ``PgEntityMergeMixin.merge_entities``: rewire
        memory links and relationship edges to the survivor, drop self-loops,
        absorb heat/recency via scalar ``MAX`` (bounded — no naive sum), archive
        the alias as a tombstone (``archived=1, heat=0``). No-op when ids match,
        an entity is missing, or either is an ``ast_symbol``.
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
        rows = self._conn.execute(
            "SELECT id, origin FROM entities WHERE id IN (?, ?)",
            (int(survivor_id), int(alias_id)),
        ).fetchall()
        origins = {r["id"]: (r["origin"] or "text_concept") for r in rows}
        if len(origins) != _MERGE_PAIR_COUNT or "ast_symbol" in origins.values():
            return result
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO memory_entities (memory_id, entity_id) "
                "SELECT memory_id, ? FROM memory_entities WHERE entity_id = ?",
                (survivor_id, alias_id),
            )
            moved = self._conn.execute(
                "DELETE FROM memory_entities WHERE entity_id = ?", (alias_id,)
            ).rowcount
            src = self._conn.execute(
                "UPDATE relationships SET source_entity_id = ? "
                "WHERE source_entity_id = ?",
                (survivor_id, alias_id),
            ).rowcount
            tgt = self._conn.execute(
                "UPDATE relationships SET target_entity_id = ? "
                "WHERE target_entity_id = ?",
                (survivor_id, alias_id),
            ).rowcount
            self._conn.execute(
                "DELETE FROM relationships "
                "WHERE source_entity_id = target_entity_id AND source_entity_id = ?",
                (survivor_id,),
            )
            self._conn.execute(
                "UPDATE entities SET "
                "heat = MAX(heat, (SELECT heat FROM entities WHERE id = ?)), "
                "last_accessed = MAX("
                "  last_accessed, (SELECT last_accessed FROM entities WHERE id = ?)) "
                "WHERE id = ?",
                (alias_id, alias_id, survivor_id),
            )
            self._conn.execute(
                "UPDATE entities SET archived = 1, heat = 0 WHERE id = ?",
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
