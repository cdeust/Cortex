"""PostgreSQL -> SQLite SQL dialect translation.

source: ADR-0604"""

from __future__ import annotations

import re
import sqlite3

# source: ADR-0604
_SUPPORTS_RETURNING = sqlite3.sqlite_version_info >= (3, 35, 0)


def _returning_was_stripped(sql: str) -> bool:
    """The caller uses it to decide whether a `None` from fetchone() means "no
        row" or "the clause was stripped, synthesise the id". It must be False
        when RETURNING survives translation, otherwise a genuinely filtered-out
        upsert (body_hash unchanged) would be reported as a write.

    source: ADR-0604"""
    return bool(re.search(r"\bRETURNING\b", sql, re.IGNORECASE)) and (
        not _SUPPORTS_RETURNING
    )


def _translate_sql(sql: str) -> str:
    """Translate psycopg-style SQL to SQLite-compatible SQL.

    source: ADR-0604"""
    # source: ADR-0604
    out = re.sub(r"%\((\w+)\)s", r":\1", sql)

    # Parameter placeholders: %s -> ?
    out = out.replace("%s", "?")

    # source: ADR-0604
    out = re.sub(r"::\w+(\s*\[\s*\])?", "", out)

    # SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
    out = re.sub(
        r"\bSERIAL\s+PRIMARY\s+KEY\b",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        out,
        flags=re.IGNORECASE,
    )

    # TIMESTAMPTZ -> TEXT
    out = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", out, flags=re.IGNORECASE)

    # DEFAULT NOW() -> DEFAULT (strftime(...))
    out = re.sub(
        r"\bDEFAULT\s+NOW\(\)",
        "DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))",
        out,
        flags=re.IGNORECASE,
    )

    # Standalone NOW() in VALUES -> strftime(...)
    out = re.sub(
        r"\bNOW\(\)",
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
        out,
        flags=re.IGNORECASE,
    )

    # source: ADR-0604
    out = re.sub(
        r"\bUPDATE\s+([\w.]+)\s+(?!AS\b|SET\b)(\w+)\s+SET\b",
        r"UPDATE \1 AS \2 SET",
        out,
        flags=re.IGNORECASE,
    )

    # `col = ANY(?)` -> `col IN (SELECT value FROM json_each(?))`. The bound
    # parameter is a Python list, which the store's adapter serialises to a
    # JSON array, so json_each expands it back into rows. Handles both the
    # positional and the named placeholder forms.
    out = re.sub(
        r"=\s*ANY\s*\(\s*(\?|:\w+)\s*\)",
        r"IN (SELECT value FROM json_each(\1))",
        out,
        flags=re.IGNORECASE,
    )

    # `col && ?` (PostgreSQL array overlap) -> a JSON intersection test.
    # Both sides are JSON arrays under SQLite (see sqlite_schema_wiki), so
    # "do these share any element" becomes a join of their json_each rows.
    # Used by get_concepts_by_entity_overlap, which drives concept emergence.
    out = re.sub(
        r"\b([a-z_][a-z0-9_.]*)\s*&&\s*\?",
        (
            r"EXISTS (SELECT 1 FROM json_each(\1) AS _ovl_l "
            r"JOIN json_each(?) AS _ovl_r ON _ovl_l.value = _ovl_r.value)"
        ),
        out,
        flags=re.IGNORECASE,
    )

    # source: ADR-0604
    out = re.sub(
        r",\s*\(\s*xmax\s*=\s*0\s*\)\s+AS\s+\w+",
        "",
        out,
        flags=re.IGNORECASE,
    )

    # source: ADR-0604
    out = re.sub(r"\bIS\s+DISTINCT\s+FROM\b", "IS NOT", out, flags=re.IGNORECASE)

    # RETURNING ... -> stripped only on runtimes without native support.
    if not _SUPPORTS_RETURNING:
        out = re.sub(r"\bRETURNING\s+\w+\b", "", out, flags=re.IGNORECASE)

    # source: ADR-0604
    out = re.sub(r"\bwiki\.([a-z_]+)", r"wiki_\1", out, flags=re.IGNORECASE)

    # source: ADR-0604
    return re.sub(
        r"\barray_length\s*\(\s*([a-z_.]+)\s*,\s*1\s*\)",
        r"json_array_length(\1)",
        out,
        flags=re.IGNORECASE,
    )
