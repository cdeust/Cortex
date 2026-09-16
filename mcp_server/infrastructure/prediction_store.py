"""Reads and writes over the `predictions` table, on either backend.

One implementation serves both: the SQLite compatibility connection
translates the `%s` placeholders and fakes `RETURNING id` from `lastrowid`,
the same way the wiki store modules are written (`pg_store_wiki_drafts`).

A row is written open and resolved once. Resolution demands a verdict, the
kind of source that settled it and a reference to that source, and the
table's own CHECK constraint refuses a resolved row without them.

source: ADR-1076"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from mcp_server.infrastructure.pg_store_wiki_common import _returning_id
from mcp_server.infrastructure.row_factory import DICT_ROW

if TYPE_CHECKING:
    from typing_extensions import LiteralString

    from mcp_server.infrastructure.db_types import StoreConnection

VERDICTS: tuple[str, ...] = ("confirmed", "refuted", "abandoned")
SOURCE_KINDS: tuple[str, ...] = ("review", "ci", "test", "manual")


def insert_prediction(conn: StoreConnection, record: dict[str, Any]) -> int:
    """Write an open prediction. Returns its id."""
    sql = """
    INSERT INTO predictions (
        claim, prediction, test, confidence, domain, directory, memory_id
    ) VALUES (
        %(claim)s, %(prediction)s, %(test)s, %(confidence)s,
        %(domain)s, %(directory)s, %(memory_id)s
    ) RETURNING id;
    """
    params = {
        "claim": record["claim"],
        "prediction": record["prediction"],
        "test": record["test"],
        "confidence": float(record["confidence"]),
        "domain": record.get("domain", ""),
        "directory": record.get("directory", ""),
        "memory_id": record.get("memory_id"),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        new_id = _returning_id(cur.fetchone())
    conn.commit()
    return new_id


def get_prediction(conn: StoreConnection, prediction_id: int) -> dict | None:
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute("SELECT * FROM predictions WHERE id = %s", (prediction_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def resolve_prediction(
    conn: StoreConnection,
    prediction_id: int,
    *,
    verdict: str,
    observed: str,
    source_kind: str,
    source_ref: str,
) -> bool:
    """Settle an open prediction. Returns False when it is already resolved.

    The caller supplies the evidence; this never fetches it.
    """
    sql = """
    UPDATE predictions
       SET status = 'resolved',
           verdict = %(verdict)s,
           observed = %(observed)s,
           source_kind = %(source_kind)s,
           source_ref = %(source_ref)s,
           resolved_at = CURRENT_TIMESTAMP
     WHERE id = %(id)s AND status = 'open'
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "id": prediction_id,
                "verdict": verdict,
                "observed": observed,
                "source_kind": source_kind,
                "source_ref": source_ref,
            },
        )
        changed = cur.rowcount
    conn.commit()
    return bool(changed)


def list_predictions(
    conn: StoreConnection,
    *,
    status: str | None = None,
    domain: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Predictions, newest first, optionally filtered by status and domain."""
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if status:
        clauses.append("status = %(status)s")
        params["status"] = status
    if domain:
        clauses.append("domain = %(domain)s")
        params["domain"] = domain
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        f"SELECT * FROM predictions {where} "  # noqa: S608 — clauses are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        "ORDER BY created_at DESC, id DESC LIMIT %(limit)s"
    )
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(cast("LiteralString", sql), params)
        return [dict(row) for row in cur.fetchall()]
