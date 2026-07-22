"""Grooming staleness reads for SqliteMemoryStore (judgment-level
curation, not the mechanical consolidate pass -- see the
core.grooming_health module docstring).

Mirror of ``PgStatsMixin.get_grooming_ages`` (pg_store_stats.py). The
jsonb tag queries translate to SQLite's ``json_each`` table-valued
function; the wiki age is an honest degradation documented on the
method. Missing entirely pre-fix: on the SQLite backend (the plugin
default) every ``store.get_grooming_ages()`` call site raised
``AttributeError`` -- observed on a real 30k-memory setup run,
2026-07-22.
"""

from __future__ import annotations

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection


class SqliteGroomingMixin:
    """Read-only grooming-age queries on SQLite."""

    _conn: PsycopgCompatConnection

    def get_grooming_ages(self) -> dict[str, str | None]:
        """Last-executed timestamp for each judgment-level grooming kind.

        Precondition: none.
        Postcondition: returns {"wiki", "distillation", "promotion"} ->
        timestamp string (ISO-8601, parseable by
        ``datetime.fromisoformat``) of the most recent judgment-level
        action of that kind recorded in this store, or None if none is
        recorded. Read-only. Same contract as
        ``PgStatsMixin.get_grooming_ages``, with one honest degradation:

        - wiki: always None. The ``tended`` timestamp lives only in the
          PG ``wiki.pages`` index (pg_store_wiki_pages.py); the SQLite
          schema has no wiki table, and wiki markdown on the filesystem
          carries no tend record this store can read. None already means
          "never recorded" to every consumer (core.grooming_health
          treats it as always-stale; ``legs_due`` additionally requires
          a non-zero backlog before nudging).
        - distillation / promotion: the SQLite translation of the PG
          jsonb queries -- 'lesson'-tagged memories carrying a
          'distill-of:'/'promoted:' tag prefix, matched via json_each.
        """
        return {
            "wiki": None,
            "distillation": self._last_lesson_tag_prefix("distill-of:"),
            "promotion": self._last_lesson_tag_prefix("promoted:"),
        }

    def _last_lesson_tag_prefix(self, prefix: str) -> str | None:
        """MAX(created_at) over 'lesson'-tagged memories with a ``prefix`` tag.

        The 'lesson' prefilter is semantically required, not an
        optimisation shortcut: curate_distill.py and lesson_promotion.py
        both only ever tag their output 'lesson', so it cannot exclude a
        true positive (same argument as the PG twin's docstring).
        """
        row = self._conn.execute(
            "SELECT MAX(m.created_at) AS last_ts FROM memories m "
            "WHERE EXISTS (SELECT 1 FROM json_each(m.tags) "
            "              WHERE value = 'lesson') "
            "AND EXISTS (SELECT 1 FROM json_each(m.tags) "
            "            WHERE value LIKE ? || '%')",
            (prefix,),
        ).fetchone()
        return row["last_ts"] if row and row["last_ts"] else None
