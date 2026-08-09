"""Ingest-progress + session-checkpoint mixin for PgMemoryStore.

Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — both tables serve the same "resume where we left
off" concern: ingest_progress for streaming ingest runs, checkpoints
for session working state.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgCheckpointMixin(PgStoreHost):
    """Ingest-run checkpoints + session checkpoints on PostgreSQL."""

    # ── Ingest checkpoint (resumable streaming ingest) ────────────────

    def get_ingest_progress(self, run_id: str) -> tuple[str, int]:
        """Return ``(last_key_committed, rows_committed)`` for ``run_id``.

        Returns ``("", 0)`` when no checkpoint exists (fresh run). A resumed
        ingest starts after ``last_key_committed``; because entity/edge writes
        are idempotent (NOT EXISTS / ON CONFLICT), an advisory — possibly one
        page stale — checkpoint is always safe.
        """
        row = self._execute(
            "SELECT last_key_committed, rows_committed FROM ingest_progress "
            "WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if not row:
            return "", 0
        return row["last_key_committed"], int(row["rows_committed"] or 0)

    def set_ingest_progress(
        self, run_id: str, last_key_committed: str, rows_committed: int
    ) -> None:
        """Upsert the ingest checkpoint for ``run_id``."""
        self._execute(
            "INSERT INTO ingest_progress "
            "(run_id, last_key_committed, rows_committed, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "last_key_committed = EXCLUDED.last_key_committed, "
            "rows_committed = EXCLUDED.rows_committed, updated_at = NOW()",
            (run_id, last_key_committed, int(rows_committed)),
        )
        self._conn.commit()

    def clear_ingest_progress(self, run_id: str) -> None:
        """Delete the checkpoint once a run completes cleanly."""
        self._execute("DELETE FROM ingest_progress WHERE run_id = %s", (run_id,))
        self._conn.commit()

    # ── Checkpoint ────────────────────────────────────────────────────

    def insert_checkpoint(self, data: dict[str, Any]) -> int:
        self._execute("UPDATE checkpoints SET is_active = FALSE")
        row = self._execute(
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
        ).one()
        self._conn.commit()
        return row["id"]

    def get_active_checkpoint(self) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM checkpoints WHERE is_active ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return self._normalize_memory_row(row) if row else None

    def get_current_epoch(self) -> int:
        row = self._execute("SELECT MAX(epoch) AS e FROM checkpoints").fetchone()
        return (row["e"] or 0) if row else 0

    def increment_epoch(self) -> int:
        new_epoch = self.get_current_epoch() + 1
        self._execute(
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
