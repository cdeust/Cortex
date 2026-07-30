"""PostgreSQL -> SQLite SQL dialect translation.

Pure string/regex rewriting, zero I/O: extracted from `sqlite_compat.py`
(issue #260) to keep that file under the project's 300-line cap
(CLAUDE.md, coding-standards §4.1) after adding the datetime-adapter fix.
`sqlite_compat.py` imports `_translate_sql`/`_returning_was_stripped` from
here for its own use; the split is behaviour-preserving — same functions,
same module-global `_SUPPORTS_RETURNING` contract, full suite green
unchanged (see the issue #260 PR).

Translations:
  - %s -> ? (parameter placeholders)
  - ::jsonb, ::TEXT, ::REAL, ::INT -> stripped (type casts)
  - SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
  - TIMESTAMPTZ -> TEXT
  - DEFAULT NOW() -> DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
  - ON CONFLICT ... DO UPDATE SET -> preserved (SQLite 3.24+)
  - RETURNING id -> stripped (use lastrowid instead)
  - wiki.<table> -> wiki_<table> (SQLite has no schema namespaces)
  - array_length(col, 1) -> json_array_length(col) (arrays are JSON TEXT)
"""

from __future__ import annotations

import re
import sqlite3

# SQLite grew RETURNING in 3.35.0 (2021-03-12).
# source: https://sqlite.org/lang_returning.html ("added in 3.35.0")
# When present we keep the clause, because upsert callers need the id of the
# row the statement actually touched: on the ON CONFLICT DO UPDATE path
# lastrowid does NOT identify the updated row, so the strip-and-synthesise
# fallback below would hand back the wrong page id. Older runtimes keep the
# historical strip behaviour.
_SUPPORTS_RETURNING = sqlite3.sqlite_version_info >= (3, 35, 0)


def _returning_was_stripped(sql: str) -> bool:
    """True when this SQL had a RETURNING clause that translation removed.

    The caller uses it to decide whether a `None` from fetchone() means "no
    row" or "the clause was stripped, synthesise the id". It must be False
    when RETURNING survives translation, otherwise a genuinely filtered-out
    upsert (body_hash unchanged) would be reported as a write.
    """
    return bool(re.search(r"\bRETURNING\b", sql, re.IGNORECASE)) and (
        not _SUPPORTS_RETURNING
    )


def _translate_sql(sql: str) -> str:
    """Translate psycopg-style SQL to SQLite-compatible SQL."""
    # Named (pyformat) placeholders: %(name)s -> :name. Must run before the
    # positional pass. The bulk claim/draft/page inserts bind by name, so
    # without this the wiki pipeline extracts zero claims and reports the
    # per-memory failure as `near "%": syntax error` (issue #206).
    out = re.sub(r"%\((\w+)\)s", r":\1", sql)

    # Parameter placeholders: %s -> ?
    out = out.replace("%s", "?")

    # Strip PostgreSQL type casts: ::jsonb, ::TEXT, ::REAL, and the ARRAY
    # forms ::int[] / ::bigint[]. The trailing [] must be consumed with the
    # cast — matching only `::int` left a stray `[]` behind, turning
    # `%s::int[]` into `?[]` and failing with a syntax error (issue #206).
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

    # `UPDATE tbl l SET ...` -> `UPDATE tbl AS l SET ...`. PostgreSQL accepts
    # a bare table alias; SQLite's UPDATE grammar requires the AS keyword.
    # (SQLite has supported UPDATE ... FROM since 3.33, so only the alias
    # spelling needs fixing.) Used by the backlink resolution pass.
    # The table may still be schema-qualified (`wiki.links`) at this point —
    # the wiki.<table> flattening runs further down — so the name pattern
    # has to admit a dot.
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

    # `(xmax = 0) AS inserted` -> dropped. xmax is a PostgreSQL system column
    # used by upsert_page to tell INSERT from UPDATE; SQLite has no analogue.
    # Dropping it is safe because no caller reads the alias — upsert_page
    # branches on whether a row came back at all, which RETURNING id alone
    # answers. Leaving it in produced `near ",": syntax error` (issue #206).
    out = re.sub(
        r",\s*\(\s*xmax\s*=\s*0\s*\)\s+AS\s+\w+",
        "",
        out,
        flags=re.IGNORECASE,
    )

    # `a IS DISTINCT FROM b` -> `a IS NOT b`: SQLite's IS/IS NOT are already
    # NULL-safe, which is exactly what IS DISTINCT FROM means.
    out = re.sub(r"\bIS\s+DISTINCT\s+FROM\b", "IS NOT", out, flags=re.IGNORECASE)

    # RETURNING ... -> stripped only on runtimes without native support.
    if not _SUPPORTS_RETURNING:
        out = re.sub(r"\bRETURNING\s+\w+\b", "", out, flags=re.IGNORECASE)

    # wiki.<table> -> wiki_<table>. SQLite has no schema namespaces, so the
    # isolated `wiki` PostgreSQL schema is flattened to a table-name prefix
    # (mcp_server/infrastructure/sqlite_schema_wiki.py declares them).
    out = re.sub(r"\bwiki\.([a-z_]+)", r"wiki_\1", out, flags=re.IGNORECASE)

    # array_length(col, 1) -> json_array_length(col). PostgreSQL INTEGER[]/
    # BIGINT[] columns are stored as JSON TEXT under SQLite; PostgreSQL
    # returns NULL for an empty array here, json_array_length returns 0 —
    # both are falsy against the `> 0` predicate every call site uses.
    return re.sub(
        r"\barray_length\s*\(\s*([a-z_.]+)\s*,\s*1\s*\)",
        r"json_array_length(\1)",
        out,
        flags=re.IGNORECASE,
    )
