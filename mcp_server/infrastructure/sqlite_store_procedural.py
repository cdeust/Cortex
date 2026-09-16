"""Procedural-memory (B1: skills/habits) mixin for SqliteMemoryStore.

The PostgreSQL counterpart is `pg_store_procedural.PgProceduralMixin`
(ADR-0558); this is the same contract on the default backend, so a session
end persists what it mined wherever Cortex runs (issue #596, ADR-1075).

source: ADR-1075"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


class SqliteProceduralMixin:
    """Procedural skill/habit CRUD on SQLite."""

    _conn: PsycopgCompatConnection

    def upsert_procedural_skill(self, data: dict[str, Any]) -> int:
        """Insert or update a mined skill, keyed by content-hash skill_id.

        Returns the row id, as the PostgreSQL mixin does.
        """
        self._conn.execute(
            "INSERT INTO procedural_skills "
            "(skill_id, action_sequence, context_signature, occurrences, "
            "success_count, failure_count, proficiency, is_habitual, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
            "ON CONFLICT (skill_id) DO UPDATE SET "
            "action_sequence = excluded.action_sequence, "
            "context_signature = excluded.context_signature, "
            "occurrences = excluded.occurrences, "
            "success_count = excluded.success_count, "
            "failure_count = excluded.failure_count, "
            "proficiency = excluded.proficiency, "
            "is_habitual = excluded.is_habitual, "
            "last_seen = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
            (
                data["skill_id"],
                data["action_sequence"],
                data.get("context_signature", ""),
                data.get("occurrences", 0),
                data.get("success_count", 0),
                data.get("failure_count", 0),
                data.get("proficiency", 0.0),
                1 if data.get("is_habitual", False) else 0,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM procedural_skills WHERE skill_id = ?",
            (data["skill_id"],),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"procedural skill {data['skill_id']!r} vanished between its "
                "upsert and its read back"
            )
        return int(row["id"])

    def get_procedural_skills(
        self, min_proficiency: float = 0.0, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Return stored skills at or above a proficiency floor, best first."""
        rows = self._conn.execute(
            "SELECT * FROM procedural_skills WHERE proficiency >= ? "
            "ORDER BY proficiency DESC, occurrences DESC LIMIT ?",
            (min_proficiency, limit),
        ).fetchall()
        return [self._as_skill(row) for row in rows]

    @staticmethod
    def _as_skill(row: Any) -> dict[str, Any]:
        """One row as the handlers read it, with the boolean back from 0/1."""
        skill = dict(row)
        skill["is_habitual"] = bool(skill.get("is_habitual", 0))
        return skill
