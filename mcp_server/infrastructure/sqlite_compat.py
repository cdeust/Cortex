"""SQLite <-> psycopg compatibility wrapper.

Translates PostgreSQL SQL conventions to SQLite equivalents so that
handler code using store._conn.execute() with psycopg-style SQL works
unchanged on the SQLite fallback backend.

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
from typing import Any


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
    out = re.sub(
        r"\barray_length\s*\(\s*([a-z_.]+)\s*,\s*1\s*\)",
        r"json_array_length(\1)",
        out,
        flags=re.IGNORECASE,
    )

    return out


class _CompatCursor:
    """Wraps a sqlite3.Cursor to mimic psycopg result access."""

    def __init__(
        self,
        cursor: sqlite3.Cursor,
        lastrowid: int,
        *,
        had_returning: bool = False,
    ) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount
        self._had_returning = had_returning

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            # Only fake {"id": lastrowid} when RETURNING was stripped
            if self._had_returning and self.lastrowid:
                return {"id": self.lastrowid}
            return None
        return dict(row) if hasattr(row, "keys") else row

    def fetchall(self) -> list:
        rows = self._cursor.fetchall()
        return [dict(r) if hasattr(r, "keys") else r for r in rows]


class _CompatExecutingCursor:
    """A psycopg-style cursor: `with conn.cursor() as cur: cur.execute(...)`.

    Distinct from _CompatCursor, which wraps a statement the connection has
    ALREADY executed. This one owns a raw cursor and translates each SQL
    string on the way in, so the wiki handlers — written against psycopg and
    shared verbatim with the PostgreSQL backend — run unmodified on SQLite.
    """

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor
        self.lastrowid: int | None = None
        self.rowcount: int = -1
        self._had_returning = False

    def __enter__(self) -> "_CompatExecutingCursor":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        self.close()
        return False

    def execute(self, sql: str, params: Any = None) -> "_CompatExecutingCursor":
        self._had_returning = _returning_was_stripped(sql)
        translated = _translate_sql(sql)
        if params:
            self._cursor.execute(translated, params)
        else:
            self._cursor.execute(translated)
        self.lastrowid = self._cursor.lastrowid
        self.rowcount = self._cursor.rowcount
        return self

    def fetchone(self) -> dict[str, Any] | None:
        row = self._cursor.fetchone()
        if row is None:
            # _translate_sql strips RETURNING, so an INSERT ... RETURNING id
            # yields no row here. pg_store_wiki_common._returning_id RAISES
            # on None, so the id must be synthesised from lastrowid or every
            # bulk insert in the wiki pipeline fails.
            if self._had_returning and self.lastrowid:
                return {"id": self.lastrowid}
            return None
        return dict(row) if hasattr(row, "keys") else row

    def fetchall(self) -> list:
        return [dict(r) if hasattr(r, "keys") else r for r in self._cursor.fetchall()]

    def close(self) -> None:
        self._cursor.close()


class PsycopgCompatConnection:
    """Wraps a sqlite3.Connection to accept psycopg-style SQL.

    Handlers that use store._conn.execute("... %s ...", (val,))
    will work transparently with this wrapper.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._real = conn

    def execute(
        self,
        sql: str,
        params: Any = None,
    ) -> _CompatCursor:
        """Execute with automatic SQL translation."""
        had_returning = _returning_was_stripped(sql)
        translated = _translate_sql(sql)
        if params:
            cur = self._real.execute(translated, params)
        else:
            cur = self._real.execute(translated)
        return _CompatCursor(
            cur,
            cur.lastrowid,
            had_returning=had_returning,
        )

    def cursor(self, row_factory: Any = None) -> _CompatExecutingCursor:
        """Return a psycopg-style cursor (context manager, translating).

        Its absence is the root cause of issue #206: the wiki pipeline's
        seven handlers all reach for `conn.cursor()`, so every stage failed
        with AttributeError on SQLite and the caller recorded it as a string.

        `row_factory` is accepted for signature parity with psycopg's
        `conn.cursor(row_factory=dict_row)` — 29 shared call sites use it —
        and is then ignored: this cursor already returns dict rows
        unconditionally, which is exactly what `dict_row` asks for. psycopg's
        other keyword, `name=` (server-side cursor), is deliberately NOT
        accepted; its single call site lives in the PgMemoryStore-only
        pg_store_queries mixin and cannot reach this class.
        """
        return _CompatExecutingCursor(self._real.cursor())

    def executescript(self, sql: str) -> None:
        """Execute multiple statements (DDL). No param translation."""
        self._real.executescript(sql)

    def commit(self) -> None:
        self._real.commit()

    def rollback(self) -> None:
        self._real.rollback()

    def close(self) -> None:
        self._real.close()

    @property
    def row_factory(self) -> Any:
        return self._real.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._real.row_factory = value

    def enable_load_extension(self, enabled: bool) -> None:
        self._real.enable_load_extension(enabled)
