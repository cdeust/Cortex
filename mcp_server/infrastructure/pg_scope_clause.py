"""PostgreSQL WHERE-clause fragment for project-directory scoping.

Mirror of sqlite_scope_clause.py for the PostgreSQL store methods
(pg_store_queries.py, pg_store_search.py) and the hooks' own raw SQL
(session_start_fetch.py, auto_recall.py, agent_briefing_*.py): one place the
predicate and its single ``ANY(%s::TEXT[])`` bind param are built, so the SQL
text can't drift between call sites (issue #604 follow-up: the predicate must
run inside the query, before ORDER BY/LIMIT, not on the already-truncated
result set).
"""

from __future__ import annotations


def normalized_directory_column(column_prefix: str = "") -> str:
    """SQL for ``directory_context`` normalized as project_scope._normalize_path.

    ``project_ancestors`` yields slash-separated paths with no trailing
    separator; ``memory_matches_project`` normalizes the stored value the same
    way. The SQL side must too, or a row recorded on Windows (``C:\\repo``)
    matches in Python and never in SQL (issue #692). ``REPLACE`` and the
    two-argument ``RTRIM`` exist with these semantics in PostgreSQL and SQLite,
    and ``'\\'`` is one backslash in both (PostgreSQL standard-conforming
    strings). No index has ``directory_context`` as a search key; SQLite's
    covering indexes that end with it (sqlite_schema.py) still yield the
    column the expression reads, so wrapping it costs no index use.

    source: ADR-1080
    source: PostgreSQL docs, functions-string (replace, rtrim)
    source: SQLite docs, lang_corefunc (replace, rtrim)
    """
    return f"RTRIM(REPLACE({column_prefix}directory_context, '\\', '/'), '/')"


def pg_scope_predicate(column_prefix: str = "") -> str:
    """The parenthesized project predicate with one ``%s`` text-array param."""
    return (
        f"({column_prefix}is_global = TRUE OR "
        f"{normalized_directory_column(column_prefix)} = ANY(%s::TEXT[]))"
    )


def directory_scope_clause(
    directory_ancestors: list[str] | None,
) -> tuple[str, tuple[list[str], ...]]:
    """SQL fragment (leading " AND ...", or "") plus its bound params.

    Precondition: directory_ancestors is None (caller wants no project
    restriction -- every other get_hot_memories/search_fts caller), an
    empty list (caller resolved no project root -- global memories only),
    or project_scope.project_ancestors(project_root)'s output.
    Postcondition: None yields ("", ()) -- unchanged query. Any list
    (including empty) yields a clause matching is_global rows or a row
    whose normalized directory_context is in the list; PostgreSQL's
    ``= ANY(...)`` is false against an empty array, so the empty-list case
    reduces to is_global-only without a separate SQL shape.
    """
    if directory_ancestors is None:
        return "", ()
    return f"AND {pg_scope_predicate()} ", (directory_ancestors,)
