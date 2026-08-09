"""Procedural-memory (B1: skills/habits) mixin for PgMemoryStore.

Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — mined skill/habit persistence is its own concern,
distinct from prospective triggers/archives/engrams.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgProceduralMixin(PgStoreHost):
    """Procedural skill/habit CRUD on PostgreSQL."""

    def upsert_procedural_skill(self, data: dict[str, Any]) -> int:
        """Insert or update a mined skill, keyed by content-hash skill_id.

        On conflict the aggregate counters are set to the incoming values
        (the miner recomputes them from the full session history each run,
        so the newest mined figures are authoritative). Returns the row id.
        The action sequence is stored as a ``>``-joined string of step keys
        (``tool`` or ``tool:target_kind``), mirroring core.procedural_memory.
        """
        row = self._execute(
            "INSERT INTO procedural_skills "
            "(skill_id, action_sequence, context_signature, occurrences, "
            "success_count, failure_count, proficiency, is_habitual, last_seen) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW()) "
            "ON CONFLICT (skill_id) DO UPDATE SET "
            "action_sequence = EXCLUDED.action_sequence, "
            "context_signature = EXCLUDED.context_signature, "
            "occurrences = EXCLUDED.occurrences, "
            "success_count = EXCLUDED.success_count, "
            "failure_count = EXCLUDED.failure_count, "
            "proficiency = EXCLUDED.proficiency, "
            "is_habitual = EXCLUDED.is_habitual, "
            "last_seen = NOW() "
            "RETURNING id",
            (
                data["skill_id"],
                data["action_sequence"],
                data.get("context_signature", ""),
                data.get("occurrences", 0),
                data.get("success_count", 0),
                data.get("failure_count", 0),
                data.get("proficiency", 0.0),
                data.get("is_habitual", False),
            ),
        ).one()
        self._conn.commit()
        return row["id"]

    def get_procedural_skills(
        self, min_proficiency: float = 0.0, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Return stored skills at or above a proficiency floor, best first."""
        rows = self._execute(
            "SELECT * FROM procedural_skills WHERE proficiency >= %s "
            "ORDER BY proficiency DESC, occurrences DESC LIMIT %s",
            (min_proficiency, limit),
        ).fetchall()
        return [dict(r) for r in rows]
