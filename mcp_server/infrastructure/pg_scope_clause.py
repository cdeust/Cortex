"""PostgreSQL WHERE-clause fragment for project-directory scoping.

Mirror of sqlite_scope_clause.py for the PostgreSQL store methods
(pg_store_queries.py, pg_store_search.py) and the two hooks' own raw SQL
(session_start.py, auto_recall.py): one place the predicate and its single
``ANY(%s::TEXT[])`` bind param are built, so the SQL text can't drift
between call sites (issue #604 follow-up: the predicate must run inside
the query, before ORDER BY/LIMIT, not on the already-truncated result set).
"""

from __future__ import annotations


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
    whose directory_context is in the list; PostgreSQL's ``= ANY(...)``
    is false against an empty array, so the empty-list case reduces to
    is_global-only without a separate SQL shape.
    """
    if directory_ancestors is None:
        return "", ()
    clause = "AND (is_global = TRUE OR directory_context = ANY(%s::TEXT[])) "
    return clause, (directory_ancestors,)
