"""Engram-slot allocation mixin for PgMemoryStore.

Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — engram slot allocation (Josselyn & Tonegawa 2020)
is its own concern, distinct from prospective/procedural/archive/
cortical-schema storage.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgEngramMixin(PgStoreHost):
    """Engram slot allocation + occupancy on PostgreSQL."""

    def init_engram_slots(self, num_slots: int) -> None:
        row = self._execute("SELECT COUNT(*) AS c FROM engram_slots").fetchone()
        existing = row["c"] if row else 0
        if existing >= num_slots:
            return
        for i in range(existing, num_slots):
            self._execute(
                "INSERT INTO engram_slots (slot_index, excitability) "
                "VALUES (%s, 0.5) ON CONFLICT DO NOTHING",
                (i,),
            )
        self._conn.commit()

    def get_all_engram_slots(self) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM engram_slots ORDER BY slot_index"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_engram_slot(self, slot_index: int) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM engram_slots WHERE slot_index = %s",
            (slot_index,),
        ).fetchone()
        return dict(row) if row else None

    def update_engram_slot(
        self, slot_index: int, excitability: float, last_activated: str
    ) -> None:
        self._execute(
            "UPDATE engram_slots SET excitability = %s, "
            "last_activated = %s WHERE slot_index = %s",
            (excitability, last_activated, slot_index),
        )
        self._conn.commit()

    def assign_memory_slot(self, memory_id: int, slot_index: int) -> None:
        self._execute(
            "UPDATE memories SET slot_index = %s WHERE id = %s",
            (slot_index, memory_id),
        )
        self._conn.commit()

    def get_memories_in_slot(self, slot_index: int) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE slot_index = %s",
            (slot_index,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def count_memories_in_slot(
        self,
        slot_index: int,
        exclude_id: int | None = None,
    ) -> int:
        """Return the number of memories assigned to *slot_index*.

        Lightweight alternative to ``get_memories_in_slot`` when only the
        count is needed (e.g. the ``temporally_linked`` metric in engram
        allocation).  *exclude_id* omits a specific memory from the count
        so the caller doesn't need to guess whether it's committed yet.
        """
        if exclude_id is not None:
            row = self._execute(
                "SELECT COUNT(*) AS c FROM memories WHERE slot_index = %s AND id != %s",
                (slot_index, exclude_id),
            ).fetchone()
        else:
            row = self._execute(
                "SELECT COUNT(*) AS c FROM memories WHERE slot_index = %s",
                (slot_index,),
            ).fetchone()
        return row["c"] if row else 0

    def get_slot_occupancy(self) -> dict[int, int]:
        rows = self._execute(
            "SELECT slot_index, COUNT(*) AS c FROM memories "
            "WHERE slot_index IS NOT NULL GROUP BY slot_index"
        ).fetchall()
        return {r["slot_index"]: r["c"] for r in rows}
