"""Atomic reconsolidation-supersession mixin for PgMemoryStore.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — the chain-head walk, the compare-and-set rebase loop, and the
anchor-transfer that must run inside the SAME transaction as the CAS
are one cohesive concern: "how a corrected memory replaces the current
head of its supersession chain without ever leaving an orphan." The
INSERT path this reuses (``_insert_memory_on``) lives in the sibling
``pg_store_write`` module.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import DictRow

from mcp_server.infrastructure.pg_store_host import PgStoreHost

# ── supersede_atomic operational bounds (engineering, not algorithmic) ──────
# Bounded optimistic-concurrency retry for the reconsolidation rebase. On the
# common single-writer path the first attempt commits; the bound only bites
# under concurrent supersession of the SAME chain, where each retry re-walks to
# the head another writer just moved. Exhausting it returns a 409-style conflict
# to the caller (nothing committed) rather than looping forever.
_SUPERSEDE_REBASE_ATTEMPTS = 5
# Defensive recursion guard for the chain-head walk. Chains are acyclic by
# construction — supersede_atomic only ever extends the OPEN head — so this cap
# is a cycle backstop, not a semantic limit on how many times a fact may be
# corrected.
_CHAIN_HEAD_MAX_DEPTH = 100_000


class _SupersedeCasConflictError(Exception):
    """The chain head moved under our compare-and-set.

    Raised inside ``_supersede_attempt`` to force a full rollback of the
    attempt (the freshly inserted row is undone — never committed, never
    orphaned) before rebasing onto the new head and retrying. Carries the
    ``head_id`` observed at the start of the failed attempt so the caller
    can update ``last_head`` before retrying.
    """

    def __init__(self, head_id: int) -> None:
        super().__init__()
        self.head_id = head_id


class PgSupersedeMixin(PgStoreHost):
    """Atomic reconsolidation-supersession (chain-head CAS + anchor transfer)."""

    def _current_chain_head(
        self, conn: psycopg.Connection[DictRow], target_id: int
    ) -> int | None:
        """Walk ``target_id``'s supersession chain to its open head.

        Follows forward ``superseded_by_id`` edges to the row whose
        superseded_by_id IS NULL — the current head. Returns that id, or None
        if ``target_id`` no longer exists. Runs on the caller's connection so
        the walk and the CAS that follows share one transaction snapshot.
        """
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
        """One supersede_atomic attempt: walk head, insert, CAS, transfer anchor.

        Returns ``None`` if ``target_id`` no longer exists (chain vanished —
        caller returns ``(None, None)`` immediately). Raises
        ``_SupersedeCasConflictError(head_id)`` if the head moved under our
        compare-and-set — caller rebases onto the new head and retries.
        Returns ``(new_id, head_id)`` on success. The whole walk+insert+CAS+
        transfer runs inside one transaction (``conn.transaction()``) so a
        conflict rolls back the freshly inserted row — never an orphan.
        """
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

        Biomimetic reconsolidation (Nader, Schafe & LeDoux 2000): a corrected
        memory is reconstructed on the CURRENT trace, never left physically
        disconnected. Each attempt (``_supersede_attempt``) inserts the new
        row and stamps the walked head's ``superseded_by_id`` — a
        compare-and-set that lands only while the head is still open. If a
        concurrent writer moved the head between the walk and the CAS, the
        whole transaction rolls back (the insert is undone — no orphan is
        ever committed) and we REBASE: re-walk ``target_id`` to the new head
        and retry, bounded by _SUPERSEDE_REBASE_ATTEMPTS. On the common path
        (no race) the head IS ``target_id`` and the first attempt commits.

        Returns ``(new_id, head_id)`` on success — ``head_id`` is the row the
        new memory now supersedes (== ``target_id`` unless a race rebased us).
        Returns ``(None, last_head_id)`` when the bounded rebase exhausts
        (pathological contention — nothing committed; the caller rebases and
        retries), or ``(None, None)`` when the target vanished mid-write.
        """
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
        """Anchor follows the chain head at supersession (decision 2026-07-07).

        A protected/anchored memory that gets superseded must keep injecting
        its CURRENT version at session start — _fetch_anchors serves chain
        heads only — so the protection flags and the anchor heat pin move to
        the new head inside the supersede transaction. GREATEST/OR semantics:
        the new row's own heat and no_decay are never lowered. The heat_base
        write is on the I2 canonical-writer allow-list
        (tests_py/invariants/test_I2_canonical_writer.py) — it cannot route
        through bump_heat_raw, which commits on its own connection while this
        transfer must stay inside the supersede transaction.
        """
        old = conn.execute(
            "SELECT no_decay, heat_base FROM memories "
            "WHERE id = %s AND is_protected = TRUE",
            (head_id,),
        ).fetchone()
        if old is None:
            return
        # heat_base first in the SET list so the I2 static scanner
        # (single-line "UPDATE memories SET heat_base") sees this writer.
        conn.execute(
            "UPDATE memories SET heat_base = GREATEST(heat_base, %s), "
            "is_protected = TRUE, no_decay = no_decay OR %s, "
            "heat_base_set_at = NOW() WHERE id = %s",
            (old["heat_base"], old["no_decay"], new_id),
        )
