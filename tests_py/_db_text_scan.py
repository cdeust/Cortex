"""Search every text cell of a Cortex store for a value.

Shared by the redaction-gate tests (ADR-1110) and the hard-forget erasure test.

Used to prove a negative: after redaction (or a hard forget) the value is in
no row of any table. The table and column lists are read from the catalog at
run time, never hard-coded, so a table added later is covered without
touching the tests.

Matching is on a normalised projection (lowercase, ``[a-z0-9]`` only): a
value that was split into tokens (the SQLite FTS augmentation appends
identifier sub-tokens such as ``ghp a 1b 2 c``) or re-cased still matches.

source: ADR-1110"""

from __future__ import annotations

import re
from typing import Any, Iterator

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def normalise(text: str) -> str:
    return _NON_ALNUM.sub("", text.lower())


def _is_sqlite(store: Any) -> bool:
    return type(store).__name__ == "SqliteMemoryStore"


def _sqlite_cells(store: Any) -> Iterator[tuple[str, str, str]]:
    conn = store._raw_conn
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    for table in tables:
        try:
            cursor = conn.execute(f'SELECT * FROM "{table}"')  # noqa: S608 — catalog name
        except Exception:  # noqa: BLE001 — a vec0 shadow table needs the extension
            continue
        columns = [d[0] for d in cursor.description]
        for row in cursor.fetchall():
            for column, value in zip(columns, row, strict=True):
                if isinstance(value, bytes):
                    value = value.decode("utf-8", "replace")
                if isinstance(value, str):
                    yield table, column, value


def _pg_cells(store: Any) -> Iterator[tuple[str, str, str]]:
    columns = store._conn.execute(
        "SELECT table_schema, table_name, column_name FROM information_schema.columns "
        "WHERE table_schema IN ('public', 'wiki') AND data_type IN "
        "('text', 'character varying', 'json', 'jsonb', 'ARRAY', 'tsvector', 'bytea')"
    ).fetchall()
    for col in columns:
        schema, table, column = (
            col["table_schema"],
            col["table_name"],
            col["column_name"],
        )
        rows = store._conn.execute(
            f'SELECT "{column}"::text AS v FROM "{schema}"."{table}"'  # noqa: S608 — catalog names
        ).fetchall()
        for row in rows:
            if row["v"] is not None:
                yield f"{schema}.{table}", column, row["v"]


def cells(store: Any) -> Iterator[tuple[str, str, str]]:
    """Every ``(table, column, text)`` cell in the store."""
    return _sqlite_cells(store) if _is_sqlite(store) else _pg_cells(store)


def locations(store: Any, value: str) -> list[tuple[str, str]]:
    """``(table, column)`` of every cell holding ``value`` (normalised match)."""
    needle = normalise(value)
    return sorted({(t, c) for t, c, text in cells(store) if needle in normalise(text)})
