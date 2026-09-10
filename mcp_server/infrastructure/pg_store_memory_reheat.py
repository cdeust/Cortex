"""source: ADR-0555"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


from mcp_server.shared.write_class import (
    NON_DELIBERATE_EXACT_SOURCES,
    NON_DELIBERATE_SOURCE_PREFIXES,
)

# source: ADR-0555
_NON_DELIBERATE_SOURCE_LIKE_PATTERNS = tuple(
    f"{prefix}%" for prefix in NON_DELIBERATE_SOURCE_PREFIXES
)

# source: ADR-0555
DEFAULT_REHEAT_SCAN_LIMIT = 5000


def list_deliberate_below_target(
    conn: StoreConnection, target: float, limit: int
) -> list[dict]:
    """List active deliberate chain-head memories with effective_heat below
    target.

    Pre-condition: target is the requested heat threshold; limit bounds
    returned rows.

    Post-condition: return dictionaries containing id, heat_base,
    effective_heat, and effective_heat_at_max. Heat uses each row domain’s
    homeostatic factor, defaulting to 1.0; effective_heat_at_max probes
    heat_base=1.0. Exclude stale rows and non-deliberate exact-source and
    prefix families. Results are ordered by id.

    source: ADR-0555"""
    sql = """
        WITH candidates AS (
            SELECT m.*
              FROM current_memories m
             WHERE NOT m.is_stale
               AND NOT (m.source = ANY(%(exact_sources)s))
               AND NOT (m.source LIKE ANY(%(prefix_patterns)s))
        ),
        probed AS (
            SELECT c.id,
                   c.heat_base::REAL AS heat_base,
                   effective_heat(c, NOW(), COALESCE(hs.factor, 1.0)::REAL)
                       AS effective_heat,
                   effective_heat(
                       jsonb_populate_record(
                           NULL::memories,
                           to_jsonb(c) || jsonb_build_object('heat_base', 1.0)
                       )::memories,
                       NOW(), COALESCE(hs.factor, 1.0)::REAL
                   ) AS effective_heat_at_max
              FROM candidates c
         -- source: ADR-0555
         LEFT JOIN homeostatic_state hs
                ON hs.domain = c.domain AND hs.write_class = 'auto'
        )
        SELECT id, heat_base, effective_heat, effective_heat_at_max
          FROM probed
         WHERE effective_heat < %(target)s
         ORDER BY id
         LIMIT %(limit)s
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(
            sql,
            {
                "exact_sources": list(NON_DELIBERATE_EXACT_SOURCES),
                "prefix_patterns": list(_NON_DELIBERATE_SOURCE_LIKE_PATTERNS),
                "target": target,
                "limit": limit,
            },
        )
        return list(cur.fetchall())


def apply_reheat(
    conn: StoreConnection, memory_id: int, old_heat_base: float, new_heat_base: float
) -> bool:
    """Compare-and-set memory_id’s heat_base to new_heat_base.

    Pre-condition: new_heat_base > old_heat_base; the caller computes and
    validates the target.

    Post-condition: return True only if the row still has old_heat_base and
    the update succeeds. Otherwise leave the row unchanged and return False.
    Never modify heat_base_set_at, consolidation_stage, or any other column.

    source: ADR-0555"""
    # source: ADR-0555
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE memories
                  SET heat_base = %(new_heat_base)s
                WHERE id = %(memory_id)s
                  AND heat_base = %(old_heat_base)s::REAL""",
            {
                "memory_id": memory_id,
                "old_heat_base": old_heat_base,
                "new_heat_base": new_heat_base,
            },
        )
        return cur.rowcount > 0


__all__ = [
    "DEFAULT_REHEAT_SCAN_LIMIT",
    "list_deliberate_below_target",
    "apply_reheat",
]
