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
from mcp_server.shared.project_scope import project_ancestors

if TYPE_CHECKING:
    from collections.abc import Iterable

    from typing_extensions import LiteralString

    from mcp_server.infrastructure.memory_store import MemoryStore


def _literal_pattern(value: str) -> str:
    return "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _contains_clause(store: MemoryStore) -> str:
    """Case-insensitive literal substring test the backend can index.

    PostgreSQL: ``ILIKE``, which ``idx_memories_content_trgm`` (gin_trgm_ops)
    serves; ``LOWER(content) LIKE`` cannot use it and scans the table.
    SQLite: ``LIKE``, which already folds ASCII case (its ``LOWER`` folds
    ASCII only too).

    source: PostgreSQL docs, pgtrgm (index support for LIKE and ILIKE)
    source: SQLite docs, lang_expr (LIKE is case-insensitive for ASCII)"""
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore  # noqa: PLC0415 — the SQLite store module imports the infrastructure stack; resolve at call time

    if isinstance(store, SqliteMemoryStore):
        return "content LIKE %s ESCAPE '!'"
    return "content ILIKE %s ESCAPE '!'"


def _boost_matching(
    store: MemoryStore,
    cues: Iterable[str],
    boost: float,
    scope: str = "",
    scope_params: tuple = (),
) -> int:
    """One UPDATE: every current, nonstale, nonbenchmark row below the heat
    cap whose content contains a cue, within ``scope``; heat capped at 1.0."""
    patterns = tuple(_literal_pattern(cue) for cue in dict.fromkeys(cues) if cue)
    if not patterns:
        return 0
    matches = " OR ".join(_contains_clause(store) for _ in patterns)
    sql = (
        "UPDATE memories SET heat_base = CASE WHEN heat_base + %s > 1.0 "  # noqa: S608 — static predicates/placeholders; all cues and project values are bound
        "THEN 1.0 ELSE heat_base + %s END, "
        "heat_base_set_at = NOW(), last_accessed = NOW() "
        "WHERE superseded_by_id IS NULL AND NOT COALESCE(is_benchmark, FALSE) "
        "AND NOT COALESCE(is_stale, FALSE) AND heat_base < 1.0 "
        f"{scope} AND ({matches})"
    )
    with store.acquire_interactive() as conn:
        try:
            # Query fragments contain only fixed SQL and generated placeholders;
            # project paths and content cues are exclusively bound parameters.
            result = conn.execute(
                cast("LiteralString", sql), (boost, boost, *scope_params, *patterns)
            )
            conn.commit()
            return result.rowcount
        except Exception:
            conn.rollback()
            raise


def prime_file_memories(
    store: MemoryStore, paths: list[str], project: str | None, boost: float
) -> int:
    """Boost each matching current row once, regardless of matching cue count."""
    cues = [cue for path in paths for cue in (path, Path(path).name)]
    scope, scope_params = directory_scope_clause(project_ancestors(project))
    return _boost_matching(store, cues, boost, scope, tuple(scope_params))


def bump_memories_mentioning(
    store: MemoryStore, symbol_names: list[str], boost: float
) -> int:
    """Boost every current row that mentions any of ``symbol_names``, once.

    No project scope and no row limit, as main's impact-bump UPDATE.

    source: ADR-0493"""
    return _boost_matching(store, symbol_names, boost)
