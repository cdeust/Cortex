"""Grooming staleness reads for SqliteMemoryStore (judgment-level
curation, not the mechanical consolidate pass -- see the
core.grooming_health module docstring).

source: ADR-0609"""

from __future__ import annotations

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


class SqliteGroomingMixin:
    """Read-only grooming-age queries on SQLite."""

    _conn: PsycopgCompatConnection

    def get_grooming_ages(self) -> dict[str, str | None]:
        """Last-executed timestamp for each judgment-level grooming kind.

        Precondition: none. Postcondition: returns {"wiki", "distillation", "promotion"}
        ->
                timestamp string (ISO-8601, parseable by
                ``datetime.fromisoformat``) of the most recent judgment-level
                action of that kind recorded in this store, or None if none is
                recorded. Read-only.

        source: ADR-0609"""
        return {
            "wiki": None,
            "distillation": self._last_lesson_tag_prefix("distill-of:"),
            "promotion": self._last_lesson_tag_prefix("promoted:"),
        }

    def _last_lesson_tag_prefix(self, prefix: str) -> str | None:
        """MAX(created_at) over 'lesson'-tagged memories with a ``prefix`` tag.

        source: ADR-0609"""
        row = self._conn.execute(
            "SELECT MAX(m.created_at) AS last_ts FROM memories m "
            "WHERE EXISTS (SELECT 1 FROM json_each(m.tags) "
            "              WHERE value = 'lesson') "
            "AND EXISTS (SELECT 1 FROM json_each(m.tags) "
            "            WHERE value LIKE ? || '%')",
            (prefix,),
        ).fetchone()
        return row["last_ts"] if row and row["last_ts"] else None
