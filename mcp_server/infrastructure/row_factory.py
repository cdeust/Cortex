"""Backend-neutral row factory for shared query modules.

A query module that takes a ``conn`` parameter may be handed either a psycopg
connection (PostgreSQL) or a ``PsycopgCompatConnection`` (SQLite). Both accept
``conn.cursor(row_factory=...)``, but only one of them can supply psycopg's
``dict_row``: psycopg ships in the optional ``[postgresql]`` extra and is
absent from the SQLite-default install every plugin/`.mcpb`/Cowork launch uses.

``from psycopg.rows import dict_row`` at the top of such a module therefore
raises ``ModuleNotFoundError`` on the default backend — and because
``wiki_pipeline`` wraps each stage in try/except, that surfaced not as a crash
but as a logged stage error with zero output: the wiki pipeline silently did
nothing on every SQLite install. Found 2026-07-28 by running the full suite
against a genuinely psycopg-less environment (issue #220); the same class of
silent degradation as the FlashRank incident.

``DICT_ROW`` resolves once, at import, and is correct on both backends:

* **PostgreSQL** — psycopg is installed, so this is exactly ``dict_row``, what
  every shared query already expects.
* **SQLite** — ``PsycopgCompatConnection.cursor()`` accepts ``row_factory``
  for signature parity and then IGNORES it, because that cursor already
  returns dict rows unconditionally (``sqlite_compat.py``, issue #206).
  ``None`` is therefore equivalent to ``dict_row`` there, not a downgrade.

Do NOT use this for ``psycopg.connect(..., row_factory=...)``: those call
sites open a real PostgreSQL connection, so psycopg is present by
construction and ``dict_row`` must be passed directly.
"""

from __future__ import annotations

from typing import Any

try:  # PostgreSQL backend — the optional [postgresql] extra is installed.
    from psycopg.rows import dict_row as _dict_row

    DICT_ROW: Any = _dict_row
except ModuleNotFoundError:  # SQLite-default install — no psycopg present.
    DICT_ROW = None

__all__ = ["DICT_ROW"]
