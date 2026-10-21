"""Atomic cue-driven heat boosts for both storage backends.

``prime_file_memories`` is the project-scoped file-cue activation (ADR-1086,
which preserves the heat increment defined by ADR-0496).
``bump_memories_mentioning`` is the pipeline impact bump (ADR-0493): main's
psycopg-only UPDATE, moved here so SQLite runs it too (issue #750).

Both send one UPDATE through the store's connection adapter: a row matching
several cues receives one increment. Matching is a case-insensitive literal
substring test the backend can index: ``ILIKE`` on PostgreSQL (served by
the trigram index; folds Unicode case), ``LIKE`` on SQLite (folds ASCII
letters only).

source: ADR-1086
source: ADR-0493
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from mcp_server.infrastructure.pg_scope_clause import directory_scope_clause
from mcp_server.infrastructure.store_operations import store_operation
from mcp_server.shared.project_scope import project_ancestors

if TYPE_CHECKING:
    from typing_extensions import LiteralString

    from mcp_server.infrastructure.memory_store import MemoryStore


def _has_cue(cues: list[str]) -> bool:
    """No cue, no request: the store is not asked for a connection."""
    return any(cues)


def _literal_pattern(value: str) -> str:
    return "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _contains_clause(conn: object) -> str:
    """Case-insensitive literal substring test the backend can index.

    PostgreSQL: ``ILIKE``, which ``idx_memories_content_trgm`` (gin_trgm_ops)
    serves; ``LOWER(content) LIKE`` cannot use it and scans the table.
    SQLite: ``LIKE``, which already folds ASCII case (its ``LOWER`` folds
    ASCII only too).

    source: PostgreSQL docs, pgtrgm (index support for LIKE and ILIKE)
    source: SQLite docs, lang_expr (LIKE is case-insensitive for ASCII)"""
    from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection  # noqa: PLC0415 — the SQLite adapter is optional at import time

    if isinstance(conn, PsycopgCompatConnection):
        return "content LIKE %s ESCAPE '!'"
    return "content ILIKE %s ESCAPE '!'"


@store_operation
def boost_matching(
    conn: object,
    cues: list[str],
    boost: float,
    project: str | None,
    scoped: bool,
) -> int:
    """One UPDATE: every current, nonstale, nonbenchmark row below the heat
    cap whose content contains a cue, within ``project``'s directory scope
    when ``scoped``; heat capped at 1.0. Returns the rows changed."""
    patterns = tuple(_literal_pattern(cue) for cue in dict.fromkeys(cues) if cue)
    if not patterns:
        return 0
    scope, scope_params = (
        directory_scope_clause(project_ancestors(project)) if scoped else ("", [])
    )
    matches = " OR ".join(_contains_clause(conn) for _ in patterns)
    sql = (
        "UPDATE memories SET heat_base = CASE WHEN heat_base + %s > 1.0 "  # noqa: S608 — static predicates/placeholders; all cues and project values are bound
        "THEN 1.0 ELSE heat_base + %s END, "
        "heat_base_set_at = NOW(), last_accessed = NOW() "
        "WHERE superseded_by_id IS NULL AND NOT COALESCE(is_benchmark, FALSE) "
        "AND NOT COALESCE(is_stale, FALSE) AND heat_base < 1.0 "
        f"{scope} AND ({matches})"
    )
    # Query fragments contain only fixed SQL and generated placeholders;
    # project paths and content cues are exclusively bound parameters.
    result = conn.execute(  # type: ignore[attr-defined]
        cast("LiteralString", sql), (boost, boost, *scope_params, *patterns)
    )
    return result.rowcount


def prime_file_memories(
    store: MemoryStore, paths: list[str], project: str | None, boost: float
) -> int:
    """Boost each matching current row once, regardless of matching cue count."""
    cues = [cue for path in paths for cue in (path, Path(path).name)]
    if not _has_cue(cues):
        return 0
    return store.call(boost_matching, cues, boost, project, True)


def bump_memories_mentioning(
    store: MemoryStore, symbol_names: list[str], boost: float
) -> int:
    """Boost every current row that mentions any of ``symbol_names``, once.

    No project scope and no row limit, as main's impact-bump UPDATE.

    source: ADR-0493"""
    if not _has_cue(symbol_names):
        return 0
    return store.call(boost_matching, list(symbol_names), boost, None, False)
