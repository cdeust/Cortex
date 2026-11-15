"""Which configured value names a PostgreSQL database (issue #704).

Pure: no I/O, stdlib only, so the per-event hooks can apply the rule
without importing the settings stack.

source: issue #704"""

from __future__ import annotations

# source: issue #704 -- the rule setup_db.py and cortex-migrate already
# applied: an unexpanded manifest interpolation is not a URL.
_PLACEHOLDER_MARK = "${"


def names_a_database(value: str | None) -> bool:
    """True when ``value`` names a database: not blank, not a placeholder.

    A value made only of whitespace names nothing: libpq reads a blank DSN
    as its local defaults, the connection issue #704 removes. A value that
    still holds ``${`` is a manifest interpolation the host left unexpanded.

    source: issue #704"""
    if not value or not value.strip():
        return False
    return _PLACEHOLDER_MARK not in value


def named_database_url(*candidates: str | None) -> str:
    """The first candidate that names a database, stripped; ``""`` when none.

    source: issue #704"""
    for candidate in candidates:
        if names_a_database(candidate):
            return candidate.strip()
    return ""
