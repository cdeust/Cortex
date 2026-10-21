"""Wiki queries that lived inside handler modules, as store operations.

Moved unchanged from ``handlers/wiki_synthesize.py``, ``wiki_refine.py``,
``wiki_resolve.py``, ``wiki_emerge.py``, ``wiki_extract.py``,
``wiki_compile.py`` and ``wiki_migrate.py`` so that no handler holds a
connection (ADR-1112 increment 2). Each function takes the connection first
and returns plain values; rows are read by key or by position because the
SQLite compatibility connection and psycopg's ``dict_row`` differ.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from mcp_server.infrastructure.row_factory import DICT_ROW
from mcp_server.infrastructure.store_operations import store_operation
from mcp_server.shared.wiki_pointer import is_pointer_source, not_a_pointer_sql
from mcp_server.shared.wiki_view_dsl import compile_view, compiled_view_ok

if TYPE_CHECKING:
    from typing_extensions import LiteralString

# source: ADR-0459 (chain heads only; pointer memories pre-filtered)
_SELECT_CANDIDATE = (
    "SELECT m.id, m.content, m.tags, m.source FROM current_memories m WHERE "
)
# source: ADR-0459
_NO_CLAIMS_YET = (
    "NOT EXISTS (SELECT 1 FROM wiki.claim_events c WHERE c.memory_id = m.id)"
)
_CLAIM_COLUMNS = (
    "id",
    "memory_id",
    "text",
    "claim_type",
    "entity_ids",
    "evidence_refs",
    "confidence",
    "supersedes",
    "extracted_at",
)
_LIST_COLUMNS = frozenset({"entity_ids", "evidence_refs"})


def _rows(conn: Any, sql: str, params: tuple) -> list[Any]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _claim_dicts(rows: list[Any], columns: tuple[str, ...]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(dict(r))
            continue
        item = {name: r[i] for i, name in enumerate(columns)}
        for name in _LIST_COLUMNS & set(columns):
            item[name] = item[name] or []
        out.append(item)
    return out


@store_operation
def memories_needing_synthesis(conn: Any, force: bool, limit: int) -> list[int]:
    """memory_ids that have claims and (unless ``force``) no template draft."""
    if force:
        sql = (
            "SELECT DISTINCT memory_id FROM wiki.claim_events"
            " WHERE memory_id IS NOT NULL ORDER BY memory_id LIMIT %s"
        )
    else:
        sql = (
            "SELECT DISTINCT c.memory_id FROM wiki.claim_events c"
            " WHERE c.memory_id IS NOT NULL AND NOT EXISTS ("
            " SELECT 1 FROM wiki.drafts d WHERE d.memory_id = c.memory_id"
            " AND d.synth_model = 'template_v1')"
            " ORDER BY c.memory_id LIMIT %s"
        )
    rows = _rows(conn, sql, (limit,))
    return [r["memory_id"] if isinstance(r, dict) else r[0] for r in rows]


@store_operation
def claims_for_memory(conn: Any, memory_id: int) -> list[dict]:
    """Every claim of ``memory_id``, in id order."""
    columns = _CLAIM_COLUMNS[:8]
    sql = (
        f"SELECT {', '.join(columns)} FROM wiki.claim_events"  # noqa: S608 — module-literal column list
        " WHERE memory_id = %s ORDER BY id"
    )
    return _claim_dicts(_rows(conn, sql, (memory_id,)), columns)


@store_operation
def claims_needing_resolution(
    conn: Any, memory_id: int | None, limit: int
) -> list[dict]:
    """Claims never resolved to entities, or every claim of ``memory_id``."""
    columns = ("id", "memory_id", "text", "claim_type", "entity_ids", "supersedes")
    select = f"SELECT {', '.join(columns)}, extracted_at FROM wiki.claim_events "  # noqa: S608 — module-literal column list
    if memory_id is not None:
        rows = _rows(conn, select + "WHERE memory_id = %s ORDER BY id", (memory_id,))
    else:
        # source: ADR-0470
        where = "WHERE COALESCE(array_length(entity_ids, 1), 0) = 0 "
        rows = _rows(conn, select + where + "ORDER BY id LIMIT %s", (limit,))
    return _claim_dicts(rows, (*columns, "extracted_at"))


@store_operation
def resolved_claims(conn: Any, limit: int) -> list[dict]:
    """claim_events that have at least one entity_id, in id order."""
    columns = ("id", "memory_id", "text", "claim_type", "entity_ids", "extracted_at")
    sql = (
        f"SELECT {', '.join(columns)} FROM wiki.claim_events"  # noqa: S608 — module-literal column list
        " WHERE entity_ids IS NOT NULL AND array_length(entity_ids, 1) > 0"
        " ORDER BY id LIMIT %s"
    )
    return _claim_dicts(_rows(conn, sql, (limit,)), columns)


@store_operation
def count_resolved_claims(conn: Any) -> int:
    """How many claims carry an entity (the cold-start test, ADR-0458)."""
    rows = _rows(
        conn,
        # Aliased: psycopg names a bare COUNT(*) "count", SQLite "COUNT(*)".
        "SELECT COUNT(*) AS count FROM wiki.claim_events"
        " WHERE entity_ids IS NOT NULL AND array_length(entity_ids, 1) > 0",
        (),
    )
    if not rows:
        return 0
    row = rows[0]
    return int(row["count"] if isinstance(row, dict) else row[0])


def _extraction_query(memory_id: int | None, limit: int, force: bool) -> tuple:
    not_pointer, pointer_params = not_a_pointer_sql("m.source")
    if memory_id is not None:
        sql = f"{_SELECT_CANDIDATE} m.id = %s AND {not_pointer}"  # noqa: S608 — module-literal fragments built by not_a_pointer_sql, not input
        return sql, (memory_id, *pointer_params)
    predicate = not_pointer if force else f"{_NO_CLAIMS_YET} AND {not_pointer}"
    sql = f"{_SELECT_CANDIDATE}{predicate} ORDER BY m.id LIMIT %s"  # noqa: S608 — module-literal fragments built by not_a_pointer_sql, not input
    return sql, (*pointer_params, limit)


@store_operation
def extraction_candidates(
    conn: Any, memory_id: int | None, limit: int, force: bool
) -> list[dict]:
    """Memory rows for claim extraction, pointer memories excluded.

    The SQL clause narrows; ``is_pointer_source`` decides (ADR-0459)."""
    sql, params = _extraction_query(memory_id, limit, force)
    out: list[dict] = []
    for r in _rows(conn, sql, params):
        if isinstance(r, dict):
            mid, content, tags, origin = (
                r["id"],
                r["content"],
                r.get("tags") or [],
                r.get("source"),
            )
        else:
            mid, content, tags, origin = r[0], r[1], r[2] or [], r[3]
        if not is_pointer_source(origin):
            out.append({"id": mid, "content": content, "tags": tags})
    return out


@store_operation
def memory_domain(conn: Any, memory_id: int | None) -> str:
    """The domain of a source memory; '_general' when absent or empty."""
    if memory_id is None:
        return "_general"
    rows = _rows(conn, "SELECT domain FROM memories WHERE id = %s", (memory_id,))
    if not rows:
        return "_general"
    row = rows[0]
    return (row["domain"] if isinstance(row, dict) else row[0]) or "_general"


@store_operation
def existing_memory_ids(conn: Any, ids: list[int]) -> list[int]:
    """The subset of ``ids`` present in ``memories`` (source: ADR-0463)."""
    if not ids:
        return []
    rows = _rows(conn, "SELECT id FROM memories WHERE id = ANY(%s)", (list(ids),))
    return [r["id"] if isinstance(r, dict) else r[0] for r in rows]


@store_operation
def execute_view(conn: Any, query_text: str) -> dict[str, Any]:
    """Compile a view with the safe DSL (table and column whitelists,
    values as bound parameters) and run it. The view text crosses the
    process boundary, never SQL: compilation happens here (ADR-0318)."""
    compiled = compile_view(query_text)
    if not compiled_view_ok(compiled):
        return {
            "error": "compile failed",
            "errors": compiled.errors,
            "sql": compiled.sql,
        }
    with conn.cursor(row_factory=DICT_ROW) as cur:
        try:
            # compiled.sql comes from the safe view compiler (ADR-0318).
            cur.execute(cast("LiteralString", compiled.sql), compiled.params)
            rows = list(cur.fetchall())
        except Exception as exc:  # noqa: BLE001 — view execution boundary — any SQL failure is returned as the view's error report
            return {"error": f"execution failed: {exc}", "sql": compiled.sql}
    return {"table": compiled.table, "rows": rows, "sql": compiled.sql}


@store_operation
def receipt_memo_exists(
    conn: Any, author: str, run_id: str, finding_id: str, stage: str
) -> bool:
    """Whether wiki.memos already records this AP receipt (wiki.memos has
    no unique constraint, so idempotence is this existence check)."""
    return bool(
        _rows(
            conn,
            "SELECT 1 FROM wiki.memos WHERE author = %s "
            "AND inputs->>'run_id' = %s AND inputs->>'finding_id' = %s "
            "AND inputs->>'stage' = %s LIMIT 1",
            (author, run_id, finding_id, stage),
        )
    )
