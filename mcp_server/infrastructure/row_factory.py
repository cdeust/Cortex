"""Backend-neutral row factory for shared query modules.

A query module that takes a ``conn`` parameter may be handed either a psycopg
connection (PostgreSQL) or a ``PsycopgCompatConnection`` (SQLite). Both accept
``conn.cursor(row_factory=...)``, but only one of them can supply psycopg's
``dict_row``: psycopg ships in the optional ``[postgresql]`` extra and is
absent from the SQLite-default install every plugin/`.mcpb`/Cowork launch uses.

``DICT_ROW`` resolves once, at import, and is correct on both backends:

Do NOT use this for ``psycopg.connect(..., row_factory=...)``: those call
sites open a real PostgreSQL connection, so psycopg is present by
construction and ``dict_row`` must be passed directly.

source: ADR-0594"""

from __future__ import annotations

from typing import Any

try:  # PostgreSQL backend — the optional [postgresql] extra is installed.
    from psycopg.rows import dict_row as _dict_row

    DICT_ROW: Any = _dict_row
except ModuleNotFoundError:  # SQLite-default install — no psycopg present.
    DICT_ROW = None

__all__ = ["DICT_ROW"]
