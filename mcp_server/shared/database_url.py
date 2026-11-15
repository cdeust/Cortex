"""Which configured value names a PostgreSQL database (issue #704).

Pure: no I/O, stdlib only, so the per-event hooks can apply the rule
without importing the settings stack.

source: issue #704"""

from __future__ import annotations

import re

# source: issue #704 -- the host interpolates the whole value, e.g.
# ``${user_config.database_url}``; left unexpanded, the value is exactly that
# token. A ``${`` inside a DSN (a literal password) is libpq's to parse.
_UNEXPANDED_PLACEHOLDER = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_.]*\}")


def names_a_database(value: str | None) -> bool:
    """True when ``value`` names a database: not blank, not a placeholder.

    A value made only of whitespace names nothing: libpq reads a blank DSN
    as its local defaults, the connection issue #704 removes. A value that is
    a whole ``${name}`` token is a manifest interpolation the host left
    unexpanded.

    source: issue #704"""
    if not value or not value.strip():
        return False
    return _UNEXPANDED_PLACEHOLDER.fullmatch(value.strip()) is None


def named_database_url(*candidates: str | None) -> str:
    """The first candidate that names a database, stripped; ``""`` when none.

    source: issue #704"""
    for candidate in candidates:
        if names_a_database(candidate):
            return candidate.strip()
    return ""
