"""Injection-receipt persistence, PostgreSQL backend.

Blame path T1/T2/T3 (decision Cortex 4255039): receipts are an
append-only record of what a channel injected into a context — there is
no update or delete surface by design. T3 adds the read path: resolving
receipt ids (handed back by the model from ⟦rcpt:id⟧ context markers)
into presence-in-context evidence.

Two write paths share the single-statement SQL below:

* ``PgReceiptsMixin.insert_injection_receipt`` — the store path used by
  the MCP recall handler (pooled connections via ``_execute``).
* ``insert_receipt_on_connection`` — the hook path (T2): SessionStart /
  UserPromptSubmit / SubagentStart hooks own a short-lived psycopg
  connection and no store instance.
"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost

# Single data-modifying-CTE statement on purpose: the store's
# ``_execute`` borrows a pool connection per call, so two separate
# INSERTs could land on two connections and lose header/items atomicity.
_INSERT_RECEIPT_SQL = (
    "WITH r AS ("
    "  INSERT INTO injection_receipts (session_id, channel)"
    "  VALUES (%s, %s) RETURNING id"
    ") "
    "INSERT INTO injection_receipt_items"
    "  (receipt_id, memory_id, rank, score) "
    "SELECT r.id, t.memory_id, t.rank, t.score "
    "FROM r, UNNEST(%s::int[], %s::int[], %s::real[])"
    "  AS t(memory_id, rank, score) "
    "RETURNING receipt_id"
)


def _receipt_params(channel: str, items: list[dict], session_id: str | None) -> tuple:
    """Coerce items into the (session_id, channel, ids, ranks, scores) tuple."""
    if not items:
        raise ValueError("injection receipt requires at least one item")  # noqa: TRY003 — one-off message; shared shape (2 occurrences, PG+SQLite backend pair) below the three-uses extraction bar (§3.3)
    memory_ids = [int(i["memory_id"]) for i in items]
    ranks = [int(i["rank"]) for i in items]
    scores = [None if i.get("score") is None else float(i["score"]) for i in items]
    return (session_id, channel, memory_ids, ranks, scores)


def insert_receipt_on_connection(
    conn,
    channel: str,
    items: list[dict],
    session_id: str | None = None,
) -> int:
    """Insert one receipt atomically on a caller-owned psycopg connection.

    Hook channels (T2) own their connection lifecycle — dict_row or
    tuple rows both work. Commit is a no-op under autocommit (the hook
    default); otherwise the receipt commits here.
    """
    row = conn.execute(
        _INSERT_RECEIPT_SQL, _receipt_params(channel, items, session_id)
    ).fetchone()
    if not getattr(conn, "autocommit", False):
        conn.commit()
    return int(row["receipt_id"] if isinstance(row, dict) else row[0])


# Read path (T3). LEFT JOIN on purpose: memory_id carries no FK — a
# memory hard-forgotten after injection must NOT erase the evidence that
# it WAS in context; such rows come back with every m.* column NULL.
# superseded_by_id is surfaced, never filtered: a receipt is historical
# evidence, and a superseded memory that was injected stays part of the
# record — the caller sees the correction state instead. Ordering is
# recorded facts only (decision 4255039): emitted_at DESC, receipt id
# DESC as the deterministic tiebreak, then the persisted injection rank.
_FETCH_RECEIPTS_SQL = (
    "SELECT r.id AS receipt_id, r.session_id, r.channel, r.emitted_at,"
    "       i.memory_id, i.rank, i.score,"
    "       m.id AS memory_row_id, m.content,"
    "       m.created_at AS memory_created_at,"
    "       m.source AS memory_source, m.domain AS memory_domain,"
    "       m.superseded_by_id "
    "FROM injection_receipts r "
    "JOIN injection_receipt_items i ON i.receipt_id = r.id "
    "LEFT JOIN memories m ON m.id = i.memory_id "
    "WHERE r.id = ANY(%s::int[]) "
    "ORDER BY r.emitted_at DESC, r.id DESC, i.rank ASC"
)


class PgReceiptsMixin(PgStoreHost):
    """Append-only injection receipts (blame path T1)."""

    def insert_injection_receipt(
        self,
        channel: str,
        items: list[dict],
        session_id: str | None = None,
    ) -> int:
        """Insert one receipt header + its items atomically; return receipt_id."""
        row = self._execute(
            _INSERT_RECEIPT_SQL, _receipt_params(channel, items, session_id)
        ).one()
        self._conn.commit()
        return int(row["receipt_id"])

    def fetch_injection_receipts(self, receipt_ids: list[int]) -> list[dict]:
        """Resolve receipt ids into flat (receipt × item × memory) rows.

        One row per injected memory, ordered by recorded facts only
        (emitted_at DESC, receipt id DESC, persisted rank ASC). Unknown
        ids simply yield no rows — the handler reports them; an empty
        input reads as an empty result (the loud non-empty contract
        lives at the tool boundary, not here).
        """
        if not receipt_ids:
            return []
        rows = self._execute(
            _FETCH_RECEIPTS_SQL, ([int(r) for r in receipt_ids],)
        ).fetchall()
        return [dict(r) for r in rows]
