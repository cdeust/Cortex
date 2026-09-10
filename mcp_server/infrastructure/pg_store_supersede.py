"""source: ADR-0570"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import DictRow

from mcp_server.infrastructure.pg_store_host import PgStoreHost

# source: ADR-0570
_SUPERSEDE_REBASE_ATTEMPTS = 5
# source: ADR-0570
_CHAIN_HEAD_MAX_DEPTH = 100_000


class _SupersedeCasConflictError(Exception):
    """The chain head moved under our compare-and-set.

    source: ADR-0570"""

    def __init__(self, head_id: int) -> None:
        super().__init__()
        self.head_id = head_id


class PgSupersedeMixin(PgStoreHost):
    """Atomic reconsolidation-supersession (chain-head CAS + anchor transfer).

    source: ADR-0570"""

    def _current_chain_head(
        self, conn: psycopg.Connection[DictRow], target_id: int
    ) -> int | None:
        """Walk ``target_id``'s supersession chain to its open head.

        source: ADR-0570"""
        row = conn.execute(
            """WITH RECURSIVE chain(id, superseded_by_id, hops) AS (
                   SELECT id, superseded_by_id, 0
                   FROM memories WHERE id = %s
                   UNION ALL
                   SELECT m.id, m.superseded_by_id, c.hops + 1
                   FROM memories m JOIN chain c ON m.id = c.superseded_by_id
                   WHERE c.hops < %s
               )
               SELECT id FROM chain
               WHERE superseded_by_id IS NULL
               ORDER BY hops DESC LIMIT 1""",
            (target_id, _CHAIN_HEAD_MAX_DEPTH),
        ).fetchone()
        return int(row["id"]) if row else None

    def _supersede_attempt(
        self, conn: psycopg.Connection[DictRow], data: dict[str, Any], target_id: int
    ) -> tuple[int, int] | None:
        """Returns ``None`` if ``target_id`` no longer exists (chain vanished —
                caller returns ``(None, None)`` immediately). Raises
                ``_SupersedeCasConflictError(head_id)`` if the head moved under our
                compare-and-set — caller rebases onto the new head and retries. Returns
                ``(new_id, head_id)`` on success.

        source: ADR-0570"""
        with conn.transaction():
            head_id = self._current_chain_head(conn, target_id)
            if head_id is None:
                return None
            data["supersedes_id"] = head_id
            new_id = self._insert_memory_on(conn, data)
            rowcount = conn.execute(
                "UPDATE memories SET superseded_by_id = %s "
                "WHERE id = %s AND superseded_by_id IS NULL",
                (new_id, head_id),
            ).rowcount
            if rowcount != 1:
                raise _SupersedeCasConflictError(head_id)
            self._transfer_anchor_on(conn, head_id, new_id)
        return new_id, head_id

    def supersede_atomic(
        self, data: dict[str, Any], target_id: int
    ) -> tuple[int | None, int | None]:
        """Insert ``data`` as the supersessor of ``target_id``'s head, atomically.

        Returns ``(new_id, head_id)`` on success — ``head_id`` is the row the
                new memory now supersedes (== ``target_id`` unless a race rebased us).
                Returns ``(None, last_head_id)`` when the bounded rebase exhausts
                (pathological contention — nothing committed; the caller rebases and
                retries), or ``(None, None)`` when the target vanished mid-write.

        source: ADR-0570"""
        last_head: int | None = None
        for _ in range(_SUPERSEDE_REBASE_ATTEMPTS):
            with self.acquire_interactive() as conn:
                try:
                    result = self._supersede_attempt(conn, data, target_id)
                except _SupersedeCasConflictError as exc:
                    last_head = exc.head_id
                    continue
                if result is None:
                    return None, None
                return result
        return None, last_head

    @staticmethod
    def _transfer_anchor_on(
        conn: psycopg.Connection[DictRow], head_id: int, new_id: int
    ) -> None:
        """Anchor follows the chain head at supersession.

        source: ADR-0570"""
        old = conn.execute(
            "SELECT no_decay, heat_base FROM memories "
            "WHERE id = %s AND is_protected = TRUE",
            (head_id,),
        ).fetchone()
        if old is None:
            return
        # source: ADR-0570
        conn.execute(
            "UPDATE memories SET heat_base = GREATEST(heat_base, %s), "
            "is_protected = TRUE, no_decay = no_decay OR %s, "
            "heat_base_set_at = NOW() WHERE id = %s",
            (old["heat_base"], old["no_decay"], new_id),
        )
