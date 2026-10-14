"""WHERE-clause filters for ``get_memories_mentioning_entity``, both stores.

The impact bump raises only memories below a heat cap, not stale and not
benchmark: the three predicates of its pre-#750 ``UPDATE``
(``git show 67a3f930:mcp_server/hooks/pipeline_impact_bump.py``). They must
filter rows before the query's LIMIT, or excluded rows fill it and starve
the rows the bump may raise (#750 review). One builder serves PostgreSQL
(``%s``) and SQLite (``?``) so both stores send the same predicates.
"""

from __future__ import annotations


def mention_filters(
    placeholder: str,
    max_heat: float | None,
    exclude_stale: bool,
    exclude_benchmark: bool,
    *,
    column_prefix: str = "",
) -> tuple[str, tuple[float, ...]]:
    """``(sql, params)``: ``AND ...`` clauses, each followed by a space, to
    place before ``ORDER BY``; ``("", ())`` when no filter is asked for.

    ``placeholder`` and ``column_prefix`` are in-code literals (``"%s"`` or
    ``"?"``; ``""`` or a table alias such as ``"m."``), never caller data.
    """
    clauses = []
    if exclude_stale:
        clauses.append(f"AND NOT {column_prefix}is_stale ")
    if exclude_benchmark:
        clauses.append(f"AND NOT {column_prefix}is_benchmark ")
    if max_heat is None:
        return "".join(clauses), ()
    clauses.append(f"AND {column_prefix}heat_base < {placeholder} ")
    return "".join(clauses), (max_heat,)
