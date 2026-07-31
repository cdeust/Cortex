"""Injection-receipt persistence, SQLite backend.

Blame path T1/T3 (decision Cortex 4255039): append-only record of what
a channel injected into a context, plus the T3 read path resolving
receipt ids into presence-in-context evidence. PG parity with
pg_store_receipts.py.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


class SqliteReceiptsMixin:
    """Append-only injection receipts (blame path T1)."""

    _conn: PsycopgCompatConnection
    _raw_conn: sqlite3.Connection

    def insert_injection_receipt(
        self,
        channel: str,
        items: list[dict],
        session_id: str | None = None,
    ) -> int:
        """Insert one receipt header + its items; return receipt_id."""
        if not items:
            raise ValueError("injection receipt requires at least one item")  # noqa: TRY003 — one-off message; shared shape (2 occurrences, PG+SQLite backend pair) below the three-uses extraction bar (§3.3)
        cur = self._raw_conn.execute(
            "INSERT INTO injection_receipts (session_id, channel) VALUES (?, ?)",
            (session_id, channel),
        )
        receipt_id = cur.lastrowid
        if receipt_id is None:
            raise sqlite3.ProgrammingError("receipt INSERT produced no lastrowid")  # noqa: TRY003 — one-off message, not reused (§3.3)
        self._raw_conn.executemany(
            "INSERT INTO injection_receipt_items"
            " (receipt_id, memory_id, rank, score) VALUES (?, ?, ?, ?)",
            [
                (
                    receipt_id,
                    int(i["memory_id"]),
                    int(i["rank"]),
                    None if i.get("score") is None else float(i["score"]),
                )
                for i in items
            ],
        )
        self._conn.commit()
        return receipt_id

    def fetch_injection_receipts(self, receipt_ids: list[int]) -> list[dict]:
        """Resolve receipt ids into flat (receipt × item × memory) rows.

        PG parity with ``PgReceiptsMixin.fetch_injection_receipts``:
        LEFT JOIN keeps evidence rows whose memory was hard-forgotten
        after injection (every m.* column NULL); superseded memories are
        surfaced with their correction state, never filtered; ordering
        replays recorded facts only (emitted_at is ISO text, so DESC is
        chronological). Empty input reads as empty output — the loud
        non-empty contract lives at the tool boundary.
        """
        if not receipt_ids:
            return []
        placeholders = ",".join("?" for _ in receipt_ids)
        rows = self._conn.execute(
            "SELECT r.id AS receipt_id, r.session_id, r.channel, r.emitted_at,"  # noqa: S608 — interpolation is a generated ?/%s placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
            "       i.memory_id, i.rank, i.score,"
            "       m.id AS memory_row_id, m.content,"
            "       m.created_at AS memory_created_at,"
            "       m.source AS memory_source, m.domain AS memory_domain,"
            "       m.superseded_by_id "
            "FROM injection_receipts r "
            "JOIN injection_receipt_items i ON i.receipt_id = r.id "
            "LEFT JOIN memories m ON m.id = i.memory_id "
            f"WHERE r.id IN ({placeholders}) "
            "ORDER BY r.emitted_at DESC, r.id DESC, i.rank ASC",
            tuple(int(r) for r in receipt_ids),
        ).fetchall()
        return [dict(r) for r in rows]
