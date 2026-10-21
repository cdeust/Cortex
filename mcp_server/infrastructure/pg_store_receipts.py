"""Injection-receipt persistence, PostgreSQL backend.

``PgReceiptsMixin.insert_injection_receipt`` is the one write path, for
the MCP recall handler and the hook channels (T2) alike: since ADR-1112
increment 2 hooks hold no connection of their own.

source: ADR-0562"""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost

# source: ADR-0562
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
        raise ValueError("injection receipt requires at least one item")
    memory_ids = [int(i["memory_id"]) for i in items]
    ranks = [int(i["rank"]) for i in items]
    scores = [None if i.get("score") is None else float(i["score"]) for i in items]
    return (session_id, channel, memory_ids, ranks, scores)


# source: ADR-0562
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

        source: ADR-0562"""
        if not receipt_ids:
            return []
        rows = self._execute(
            _FETCH_RECEIPTS_SQL, ([int(r) for r in receipt_ids],)
        ).fetchall()
        return [dict(r) for r in rows]
