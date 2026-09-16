"""SQLite DDL for procedural memory, the B1 skills table.

The table existed only on PostgreSQL (`pg_schema.PROCEDURAL_SKILLS_DDL`,
ADR-0558), so on the default backend the session-end writer mined its skills
and then lost every one of them to an `AttributeError` the caller swallowed
(issue #596). The columns mirror the PostgreSQL ones exactly, with SQLite's
spellings: INTEGER PRIMARY KEY for the serial, INTEGER for the boolean, and
ISO-8601 text for the timestamps, as the rest of this schema does.

source: ADR-1075"""

from __future__ import annotations

PROCEDURAL_SKILLS_DDL = """
CREATE TABLE IF NOT EXISTS procedural_skills (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id            TEXT NOT NULL UNIQUE,
    action_sequence     TEXT NOT NULL,
    context_signature   TEXT NOT NULL DEFAULT '',
    occurrences         INTEGER NOT NULL DEFAULT 0,
    success_count       INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    proficiency         REAL NOT NULL DEFAULT 0.0,
    is_habitual         INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

PROCEDURAL_INDEXES_DDL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_procedural_proficiency "
    "ON procedural_skills (proficiency DESC, occurrences DESC)",
]


def get_procedural_ddl() -> list[str]:
    """Every procedural-memory statement, in execution order."""
    return [PROCEDURAL_SKILLS_DDL, *PROCEDURAL_INDEXES_DDL]
