"""Auxiliary persistence mixin: prospective memories, checkpoints, archives, engrams."""

from __future__ import annotations

import json
from typing import Any

import psycopg


class PgAuxiliaryMixin:
    """Prospective memory, checkpoint, archive, engram operations on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    # ── Prospective Memory ────────────────────────────────────────────

    def insert_prospective_memory(self, data: dict[str, Any]) -> int:
        row = self._conn.execute(
            "INSERT INTO prospective_memories "
            "(content, trigger_condition, trigger_type, "
            "target_directory, is_active, triggered_count) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (
                data["content"],
                data["trigger_condition"],
                data["trigger_type"],
                data.get("target_directory"),
                data.get("is_active", True),
                data.get("triggered_count", 0),
            ),
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_active_prospective_memories(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM prospective_memories WHERE is_active"
        ).fetchall()
        return [dict(r) for r in rows]

    def trigger_prospective_memory(self, pm_id: int) -> None:
        self._conn.execute(
            "UPDATE prospective_memories SET triggered_at = NOW(), "
            "triggered_count = triggered_count + 1 WHERE id = %s",
            (pm_id,),
        )
        self._conn.commit()

    def deactivate_prospective_memory(self, pm_id: int) -> None:
        self._conn.execute(
            "UPDATE prospective_memories SET is_active = FALSE WHERE id = %s",
            (pm_id,),
        )
        self._conn.commit()

    # ── Checkpoint ────────────────────────────────────────────────────

    def insert_checkpoint(self, data: dict[str, Any]) -> int:
        self._conn.execute("UPDATE checkpoints SET is_active = FALSE")
        row = self._conn.execute(
            "INSERT INTO checkpoints "
            "(session_id, directory_context, current_task, "
            "files_being_edited, key_decisions, open_questions, "
            "next_steps, active_errors, custom_context, epoch, is_active) "
            "VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, "
            "%s::jsonb, %s::jsonb, %s, %s, TRUE) RETURNING id",
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
            ),
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_active_checkpoint(self) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE is_active ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return self._normalize_memory_row(row) if row else None

    def get_current_epoch(self) -> int:
        row = self._conn.execute("SELECT MAX(epoch) AS e FROM checkpoints").fetchone()
        return (row["e"] or 0) if row else 0

    def increment_epoch(self) -> int:
        new_epoch = self.get_current_epoch() + 1
        self._conn.execute(
            "INSERT INTO checkpoints "
            "(session_id, directory_context, current_task, "
            "files_being_edited, key_decisions, open_questions, "
            "next_steps, active_errors, custom_context, epoch, is_active) "
            "VALUES ('epoch-sentinel', '', %s, '[]'::jsonb, '[]'::jsonb, "
            "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '', %s, FALSE)",
            (f"epoch-boundary:{new_epoch}", new_epoch),
        )
        self._conn.commit()
        return new_epoch

    # ── Archive ───────────────────────────────────────────────────────

    def insert_archive(self, data: dict[str, Any]) -> int:
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        emb = PgMemoryStore._bytes_to_vector(data.get("embedding"))
        row = self._conn.execute(
            "INSERT INTO memory_archives "
            "(original_memory_id, content, embedding, "
            "mismatch_score, archive_reason) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (
                data["original_memory_id"],
                data["content"],
                emb,
                data.get("mismatch_score", 0.0),
                data.get("archive_reason", ""),
            ),
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_archives_for_memory(self, memory_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memory_archives "
            "WHERE original_memory_id = %s ORDER BY archived_at DESC",
            (memory_id,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    # ── Engram Slots ──────────────────────────────────────────────────

    def init_engram_slots(self, num_slots: int) -> None:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM engram_slots").fetchone()
        existing = row["c"] if row else 0
        if existing >= num_slots:
            return
        for i in range(existing, num_slots):
            self._conn.execute(
                "INSERT INTO engram_slots (slot_index, excitability) "
                "VALUES (%s, 0.5) ON CONFLICT DO NOTHING",
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
            "SELECT * FROM engram_slots WHERE slot_index = %s",
            (slot_index,),
        ).fetchone()
        return dict(row) if row else None

    def update_engram_slot(
        self, slot_index: int, excitability: float, last_activated: str
    ) -> None:
        self._conn.execute(
            "UPDATE engram_slots SET excitability = %s, "
            "last_activated = %s WHERE slot_index = %s",
            (excitability, last_activated, slot_index),
        )
        self._conn.commit()

    def assign_memory_slot(self, memory_id: int, slot_index: int) -> None:
        self._conn.execute(
            "UPDATE memories SET slot_index = %s WHERE id = %s",
            (slot_index, memory_id),
        )
        self._conn.commit()

    def get_memories_in_slot(self, slot_index: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE slot_index = %s",
            (slot_index,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_slot_occupancy(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT slot_index, COUNT(*) AS c FROM memories "
            "WHERE slot_index IS NOT NULL GROUP BY slot_index"
        ).fetchall()
        return {r["slot_index"]: r["c"] for r in rows}

    # ── Schemas (cortical structures) ─────────────────────────────────

    def insert_schema(self, data: dict[str, Any]) -> int:
        try:
            row = self._conn.execute(
                """INSERT INTO schemas (
                    schema_id, domain, label, entity_signature,
                    relationship_types, tag_signature,
                    consistency_threshold, formation_count,
                    assimilation_count, violation_count
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                          %s, %s, %s, %s) RETURNING id""",
                (
                    data["schema_id"],
                    data.get("domain", ""),
                    data.get("label", ""),
                    json.dumps(data.get("entity_signature", {})),
                    json.dumps(data.get("relationship_types", [])),
                    json.dumps(data.get("tag_signature", {})),
                    data.get("consistency_threshold", 0.7),
                    data.get("formation_count", 0),
                    data.get("assimilation_count", 0),
                    data.get("violation_count", 0),
                ),
            ).fetchone()
            self._conn.commit()
            return row["id"]
        except psycopg.errors.UniqueViolation:
            self._conn.rollback()
            return self._update_existing_schema(data)

    def _update_existing_schema(self, data: dict[str, Any]) -> int:
        self._conn.execute(
            """UPDATE schemas SET
                domain = %s, label = %s, entity_signature = %s::jsonb,
                relationship_types = %s::jsonb, tag_signature = %s::jsonb,
                consistency_threshold = %s, formation_count = %s,
                assimilation_count = %s, violation_count = %s,
                last_updated = NOW()
            WHERE schema_id = %s""",
            (
                data.get("domain", ""),
                data.get("label", ""),
                json.dumps(data.get("entity_signature", {})),
                json.dumps(data.get("relationship_types", [])),
                json.dumps(data.get("tag_signature", {})),
                data.get("consistency_threshold", 0.7),
                data.get("formation_count", 0),
                data.get("assimilation_count", 0),
                data.get("violation_count", 0),
                data["schema_id"],
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM schemas WHERE schema_id = %s",
            (data["schema_id"],),
        ).fetchone()
        return row["id"] if row else 0

    def get_schemas_for_domain(self, domain: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM schemas WHERE domain = %s ORDER BY formation_count DESC",
            (domain,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_schemas(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM schemas ORDER BY formation_count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def count_schemas(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM schemas").fetchone()
        return row["c"] if row else 0

    def delete_schema(self, schema_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM schemas WHERE schema_id = %s", (schema_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0
