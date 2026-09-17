"""SQLite WHERE-clause fragment for project-directory scoping.

One place both ``get_hot_memories`` and ``search_fts`` (sqlite_store_queries.py,
sqlite_store_search.py) build the predicate from, so the SQL text and the bind
order can't drift between the two call sites (issue #604 follow-up: the
predicate must run inside the query, before ORDER BY/LIMIT, not on the
already-truncated result set).
"""

from __future__ import annotations


def directory_scope_clause(
    directory_ancestors: list[str] | None,
    column_prefix: str = "",
) -> tuple[str, tuple[str, ...]]:
    """SQL fragment (leading " AND ...", or "") plus its bound params.

    Precondition: directory_ancestors is None (caller wants no project
    restriction at all -- every other get_hot_memories/search_fts caller),
    an empty list (caller resolved no project root -- global memories
    only), or project_scope.project_ancestors(project_root)'s output.
    column_prefix is a table alias plus "." (e.g. "m.") for queries that
    join and would otherwise have an ambiguous column name; "" when the
    query has one table in scope.
    Postcondition: None yields ("", ()) -- unchanged query, backward
    compatible with every existing caller. An empty list yields a clause
    matching only is_global rows. A non-empty list yields a clause
    matching is_global rows or any row whose directory_context is in the
    list.
    """
    if directory_ancestors is None:
        return "", ()
    if not directory_ancestors:
        return f"AND {column_prefix}is_global = 1 ", ()
    placeholders = ",".join("?" for _ in directory_ancestors)
    clause = (
        f"AND ({column_prefix}is_global = 1 OR "
        f"{column_prefix}directory_context IN ({placeholders})) "
    )
    return clause, tuple(directory_ancestors)
