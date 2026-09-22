"""Atomic, project-scoped file-cue activation for both storage backends.

source: ADR-1086
preserves the heat increment defined by ADR-0496.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_scope_clause import directory_scope_clause
from mcp_server.shared.project_scope import project_ancestors


def _literal_pattern(value: str) -> str:
    return "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def prime_file_memories(
    store: MemoryStore, paths: list[str], project: str | None, boost: float
) -> int:
    """Boost each matching current row once, regardless of matching cue count."""
    cues = dict.fromkeys(
        cue for path in paths for cue in (path, Path(path).name) if cue
    )
    if not cues:
        return 0
    matches = " OR ".join("LOWER(content) LIKE LOWER(%s) ESCAPE '!'" for _ in cues)
    scope, scope_params = directory_scope_clause(project_ancestors(project))
    sql = (
        "UPDATE memories SET heat_base = CASE WHEN heat_base + %s > 1.0 "  # noqa: S608 — static predicates/placeholders; all cues and project values are bound
        "THEN 1.0 ELSE heat_base + %s END, "
        "heat_base_set_at = NOW(), last_accessed = NOW() "
        "WHERE superseded_by_id IS NULL AND NOT COALESCE(is_benchmark, FALSE) "
        "AND NOT COALESCE(is_stale, FALSE) AND heat_base < 1.0 "
        f"{scope} AND ({matches})"
    )
    params = (boost, boost, *scope_params, *(_literal_pattern(cue) for cue in cues))
    with store.acquire_interactive() as conn:
        try:
            result = conn.execute(sql, params)
            conn.commit()
            return result.rowcount
        except Exception:
            conn.rollback()
            raise
