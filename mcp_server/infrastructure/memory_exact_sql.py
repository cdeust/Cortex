"""Shared exact-text and scope predicates for replay persistence (#707).

No window functions, UPDATE FROM, MATERIALIZED or RETURNING are required.
source: https://www.sqlite.org/lang_update.html
source: https://www.postgresql.org/docs/current/explicit-locking.html
"""

from __future__ import annotations

from typing import Any, cast, TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    from mcp_server.infrastructure.db_types import StoreConnection

_SCOPE = (
    ("domain", ""),
    ("directory_context", ""),
    ("agent_context", ""),
    ("source", ""),
    ("write_class", "deliberate"),
    ("capture_origin", "unknown"),
    ("is_global", False),
    ("is_team_decision", False),
)

_LIVE = (
    "superseded_by_id IS NULL AND NOT COALESCE(is_stale, FALSE) "
    "AND NOT COALESCE(is_benchmark, FALSE) AND /* replica */ TRUE"
)


def bypass(data: dict[str, Any]) -> bool:
    return bool(data.get("is_benchmark")) or "memory-replica" in (
        data.get("tags") or []
    )


def scope_columns() -> str:
    """SQL fragments contain only the fixed schema vocabulary above."""
    return ", ".join(
        f"COALESCE({name}, {'FALSE' if default is False else repr(default)})"
        for name, default in _SCOPE
    )


def predicate(sqlite: bool, *, live: bool = True) -> LiteralString:
    scope = " AND ".join(
        f"COALESCE({name}, {'FALSE' if default is False else repr(default)}) = %s"
        for name, default in _SCOPE
    )
    text = "content = %s" if sqlite else "md5(content) = md5(%s) AND content = %s"
    replica = (
        "NOT EXISTS (SELECT 1 FROM json_each(tags) WHERE value = 'memory-replica')"
        if sqlite
        else "NOT COALESCE(tags @> '[\"memory-replica\"]'::jsonb, FALSE)"
    )
    eligible = (
        _LIVE if live else "NOT COALESCE(is_benchmark, FALSE) AND /* replica */ TRUE"
    )
    return cast(
        "LiteralString",
        f"{text} AND {scope} AND {eligible.replace('/* replica */ TRUE', replica)}",
    )


def params(data: dict[str, Any], sqlite: bool) -> tuple[Any, ...]:
    content = (data["content"],) if sqlite else (data["content"], data["content"])
    return content + tuple(data.get(name) or default for name, default in _SCOPE)


def candidates_sql(sqlite: bool) -> LiteralString:
    """Group by the identical text/scope key used by the locked lookup."""
    replica = (
        "NOT EXISTS (SELECT 1 FROM json_each(tags) WHERE value = 'memory-replica')"
        if sqlite
        else "NOT COALESCE(tags @> '[\"memory-replica\"]'::jsonb, FALSE)"
    )
    group = "content, " + scope_columns()
    if not sqlite:
        group = "md5(content), " + group
    return cast(
        "LiteralString",
        "SELECT MIN(id) AS id FROM memories WHERE "  # noqa: S608 -- schema literals only; values are bound
        + _LIVE.replace("/* replica */ TRUE", replica)
        + " GROUP BY "
        + group
        + " HAVING COUNT(*) > 1 ORDER BY MIN(id)",
    )


def find_on(conn: StoreConnection, data: dict[str, Any], sqlite: bool) -> int | None:
    if bypass(data):
        return None
    query = cast(
        "LiteralString",
        "SELECT id FROM memories WHERE " + predicate(sqlite) + " ORDER BY id LIMIT 1",  # noqa: S608 -- fixed schema predicate; values are bound
    )
    row = conn.execute(query, params(data, sqlite)).fetchone()
    return int(row["id"]) if row else None


def collapse_group(conn: StoreConnection, data: dict[str, Any], sqlite: bool) -> int:
    """Recheck a candidate under its backend lock and update only that group.

    source: issue #707: protected/no-decay rows win, then heat, age and id.
    """
    query = (
        "SELECT id, is_protected, no_decay FROM memories WHERE "  # noqa: S608 -- fixed schema predicate; values are bound
        + predicate(sqlite)
        + " ORDER BY COALESCE(is_protected, FALSE) DESC, "
        "COALESCE(no_decay, FALSE) DESC, heat_base DESC, created_at, id"
    )
    if not sqlite:
        query += " FOR UPDATE NOWAIT"
    rows = conn.execute(cast("LiteralString", query), params(data, sqlite)).fetchall()
    if len(rows) <= 1:
        return 0
    survivor = rows[0]["id"]
    conn.execute(
        "UPDATE memories SET is_protected = %s, no_decay = %s WHERE id = %s",
        (
            any(r["is_protected"] for r in rows),
            any(r["no_decay"] for r in rows),
            survivor,
        ),
    )
    # Only rows observed under the lock may be changed, including for raw writers.
    result = conn.execute(
        "UPDATE memories SET superseded_by_id = %s "
        "WHERE id = ANY(%s) AND superseded_by_id IS NULL",
        (survivor, [row["id"] for row in rows[1:]]),
    )
    return result.rowcount
