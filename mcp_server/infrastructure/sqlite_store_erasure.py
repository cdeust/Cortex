"""SQLite half of hard forget: one transaction over every copy, then the file.

A deleted row's bytes stay in SQLite's free pages, in the FTS5 index segments
and in the WAL until something overwrites them. Erasure therefore relies on
``PRAGMA secure_delete = ON`` (every connection, set by the connection
registry), FTS5's ``secure-delete`` option (SQLite 3.42+, enabled before the
first erasure and persistent in the index; on an older library an FTS5
``optimize`` merge, run inside the erasure transaction, rewrites the index
without the deleted entries) and a ``TRUNCATE`` WAL checkpoint after the
commit, whose failure is reported as residue (``ErasureReport``).

source: ADR-1111"""

from __future__ import annotations

import sqlite3
from typing import Any

from mcp_server.infrastructure.memory_erasure import (
    ErasureReport,
    erase_derived_rows,
    erase_entities,
    erase_pages,
)
from mcp_server.shared.wiki_pointer import is_pointer_source

_CONCEPT_GROUNDING = (
    "UPDATE wiki.concepts SET grounding_memory_ids = ("
    "SELECT json_group_array(value) FROM json_each(grounding_memory_ids) "
    "WHERE value <> %s) "
    "WHERE EXISTS (SELECT 1 FROM json_each(grounding_memory_ids) WHERE value = %s)"
)


def enable_fts_secure_delete(conn: Any) -> bool:
    """Ask FTS5 to drop deleted entries from its index; False if unsupported."""
    try:
        conn.execute(
            "INSERT INTO memories_fts(memories_fts, rank) VALUES('secure-delete', 1)"
        )
    except sqlite3.OperationalError:
        return False
    return True


class SqliteErasureMixin:
    _conn: Any
    _has_vec: bool

    def erase_memory(self, memory_id: int) -> ErasureReport:
        """Delete the memory and every row holding a copy of its text.

        Raises (and erases nothing) if any statement before the commit fails;
        a WAL truncation that fails after it is reported as residue."""
        report = ErasureReport()
        row = self._conn.execute(
            "SELECT source FROM memories WHERE id = %s", (memory_id,)
        ).fetchone()
        if row is None:
            return report
        secure = enable_fts_secure_delete(self._conn)
        try:
            self._erase_rows(memory_id, row["source"], report)
            report.fts_method = self._purge_fts(secure)
        except BaseException:
            self._conn.rollback()
            raise
        self._conn.commit()
        report.wal_truncated = report.after_commit("wal", self._truncate_wal, False)
        return report

    def _erase_rows(self, memory_id: int, source: str, report: ErasureReport) -> None:
        erase_derived_rows(self._conn, memory_id, report)
        if not is_pointer_source(source):
            erase_pages(self._conn, memory_id, report)
        erase_entities(self._conn, memory_id, report)
        self._conn.execute(_CONCEPT_GROUNDING, (memory_id, memory_id))
        self._conn.execute("DELETE FROM memories_fts WHERE rowid = %s", (memory_id,))
        if self._has_vec:
            self._conn.execute(
                "DELETE FROM memories_vec WHERE rowid = %s", (memory_id,)
            )
        cur = self._conn.execute("DELETE FROM memories WHERE id = %s", (memory_id,))
        report.deleted = cur.rowcount > 0

    def _purge_fts(self, secure: bool) -> str:
        """Inside the erasure transaction: rewrite the FTS index when the
        library cannot drop deleted entries on its own."""
        if secure:
            return "secure-delete"
        self._conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('optimize')")
        return "optimize"

    def _truncate_wal(self) -> bool:
        """``wal_checkpoint(TRUNCATE)``; True when no reader blocked it."""
        row = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return row is not None and not list(dict(row).values())[0]
