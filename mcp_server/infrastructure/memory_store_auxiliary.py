"""Auxiliary persistence mixin: prospective memories, checkpoints, archives, engrams."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


class MemoryAuxiliaryMixin:
    """Prospective memory, checkpoint, archive, and engram slot operations.

    Requires _conn (sqlite3.Connection) and _row_to_dict on the host class.
    """

    _conn: sqlite3.Connection

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Prospective Memory ─────────────────────────────────────────────

    def insert_prospective_memory(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        cursor = self._conn.execute(
            "INSERT INTO prospective_memories "
            "(content, trigger_condition, trigger_type, "
            "target_directory, is_active, created_at, triggered_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                data["content"],
                data["trigger_condition"],
                data["trigger_type"],
                data.get("target_directory"),
                1 if data.get("is_active", True) else 0,
                data.get("created_at", now),
                data.get("triggered_count", 0),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_active_prospective_memories(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM prospective_memories WHERE is_active = 1"
        ).fetchall()
        return [dict(r) for r in rows]

    def trigger_prospective_memory(self, pm_id: int) -> None:
        now = self._now_iso()
        self._conn.execute(
            "UPDATE prospective_memories SET triggered_at = ?, "
            "triggered_count = triggered_count + 1 WHERE id = ?",
            (now, pm_id),
        )
        self._conn.commit()

    def deactivate_prospective_memory(self, pm_id: int) -> None:
        self._conn.execute(
            "UPDATE prospective_memories SET is_active = 0 WHERE id = ?",
            (pm_id,),
        )
        self._conn.commit()

    # ── Checkpoint ─────────────────────────────────────────────────────

    def insert_checkpoint(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        self._conn.execute("UPDATE checkpoints SET is_active = 0")
        cursor = self._conn.execute(
            "INSERT INTO checkpoints "
            "(session_id, directory_context, current_task, "
            "files_being_edited, key_decisions, open_questions, "
            "next_steps, active_errors, custom_context, epoch, "
            "created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (
                data.get("session_id", "default"),
                data.get("directory_context", ""),
                data.get("current_task", ""),
                json.dumps(data.get("files_being_edited", [])),
                json.dumps(data.get("key_decisions", [])),
                json.dumps(data.get("open_questions", [])),
                json.dumps(data.get("next_steps", [])),
                json.dumps(data.get("active_errors", [])),
                data.get("custom_context", ""),
                data.get("epoch", 0),
                now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_active_checkpoint(self) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE is_active = 1 "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return self._row_to_dict(row)

    def get_current_epoch(self) -> int:
        row = self._conn.execute("SELECT MAX(epoch) as e FROM checkpoints").fetchone()
        return (row["e"] or 0) if row else 0

    def increment_epoch(self) -> int:
        """Increment the epoch counter and return the new value."""
        new_epoch = self.get_current_epoch() + 1
        self._conn.execute(
            "INSERT INTO checkpoints "
            "(session_id, directory_context, current_task, "
            "files_being_edited, key_decisions, open_questions, "
            "next_steps, active_errors, custom_context, epoch, "
            "created_at, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                "epoch-sentinel",
                "",
                f"epoch-boundary:{new_epoch}",
                "[]",
                "[]",
                "[]",
                "[]",
                "[]",
                "",
                new_epoch,
                self._now_iso(),
            ),
        )
        self._conn.commit()
        return new_epoch

    # ── Archive ────────────────────────────────────────────────────────

    def insert_archive(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        cursor = self._conn.execute(
            "INSERT INTO memory_archives "
            "(original_memory_id, content, embedding, archived_at, "
            "mismatch_score, archive_reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                data["original_memory_id"],
                data["content"],
                data.get("embedding"),
                now,
                data.get("mismatch_score", 0.0),
                data.get("archive_reason", ""),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_archives_for_memory(self, memory_id: int) -> list[dict[str, Any]]:
        """Get all archives for a memory, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM memory_archives "
            "WHERE original_memory_id = ? "
            "ORDER BY archived_at DESC",
            (memory_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── Engram Slots ───────────────────────────────────────────────────

    def init_engram_slots(self, num_slots: int) -> None:
        existing = self._conn.execute(
            "SELECT COUNT(*) as c FROM engram_slots"
        ).fetchone()
        if existing["c"] >= num_slots:
            return
        for i in range(existing["c"], num_slots):
            self._conn.execute(
                "INSERT OR IGNORE INTO engram_slots "
                "(slot_index, excitability) VALUES (?, 0.5)",
                (i,),
            )
        self._conn.commit()

    def get_all_engram_slots(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM engram_slots ORDER BY slot_index"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_engram_slot(self, slot_index: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM engram_slots WHERE slot_index = ?",
            (slot_index,),
        ).fetchone()
        return dict(row) if row else None

    def update_engram_slot(
        self, slot_index: int, excitability: float, last_activated: str
    ) -> None:
        self._conn.execute(
            "UPDATE engram_slots SET excitability = ?, "
            "last_activated = ? WHERE slot_index = ?",
            (excitability, last_activated, slot_index),
        )
        self._conn.commit()

    def assign_memory_slot(self, memory_id: int, slot_index: int) -> None:
        self._conn.execute(
            "UPDATE memories SET slot_index = ? WHERE id = ?",
            (slot_index, memory_id),
        )
        self._conn.commit()

    def get_memories_in_slot(self, slot_index: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE slot_index = ?",
            (slot_index,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_slot_occupancy(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT slot_index, COUNT(*) as c FROM memories "
            "WHERE slot_index IS NOT NULL GROUP BY slot_index"
        ).fetchall()
        return {r["slot_index"]: r["c"] for r in rows}
