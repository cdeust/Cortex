"""The only place a database connection is constructed (ADR-1110).

Every connection Cortex opens comes from here, so every connection is of a
gated class: SQLite connections are ``GatedConnection``s, PostgreSQL
connections and pool connections hand out ``GatedCursor``s returning dict
rows. A caller cannot ask for another class, and ``tests_py/architecture``
fails on any other connection constructor in ``mcp_server/``. A connection
that crosses a module boundary (a hook passing its connection to a receipt
writer, a handler borrowing a pool connection) is therefore gated whatever
reads or writes through it. psycopg's ``Connection.cursor()`` takes no
cursor class argument; a named cursor (``cursor(name=...)``) is a server-side
``DECLARE ... CURSOR``, which PostgreSQL accepts only for a SELECT or VALUES
query, so it cannot write.

source: ADR-1110"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any

from mcp_server.infrastructure.sqlite_gated_connection import GatedConnection

if TYPE_CHECKING:
    import psycopg
    from psycopg.rows import DictRow
    from psycopg_pool import ConnectionPool


def _refuse_factory(kwargs: dict[str, Any], name: str) -> None:
    if name in kwargs:
        raise TypeError(f"{name} is fixed by db_connect; connections are always gated")


def sqlite_connect(target: str, **kwargs: Any) -> GatedConnection:
    """``sqlite3.connect`` returning a :class:`GatedConnection`."""
    _refuse_factory(kwargs, "factory")
    return sqlite3.connect(target, factory=GatedConnection, **kwargs)  # type: ignore[return-value]


def pg_connect(url: str, **kwargs: Any) -> "psycopg.Connection[DictRow]":
    """A psycopg connection whose cursors are gated and whose rows are dicts.

    A caller-chosen factory is refused before the driver is imported, so the
    refusal holds on an install without the [postgresql] extra too."""
    _refuse_factory(kwargs, "cursor_factory")
    _refuse_factory(kwargs, "row_factory")
    import psycopg  # noqa: PLC0415 — optional [postgresql] extra; SQLite installs never reach here
    from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — same

    from mcp_server.infrastructure.pg_gated_cursor import GatedCursor  # noqa: PLC0415 — imports psycopg

    return psycopg.Connection[DictRow].connect(
        url, cursor_factory=GatedCursor, row_factory=dict_row, **kwargs
    )


def pg_pool(
    url: str, *, kwargs: dict[str, Any], **options: Any
) -> "ConnectionPool[psycopg.Connection[DictRow]]":
    """A psycopg pool whose every connection hands out gated cursors and dict
    rows."""
    _refuse_factory(kwargs, "cursor_factory")
    _refuse_factory(kwargs, "row_factory")
    import psycopg  # noqa: PLC0415 — optional [postgresql] extra
    from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — same
    from psycopg_pool import ConnectionPool  # noqa: PLC0415 — same

    from mcp_server.infrastructure.pg_gated_cursor import GatedCursor  # noqa: PLC0415 — imports psycopg

    gated = {**kwargs, "cursor_factory": GatedCursor, "row_factory": dict_row}
    return ConnectionPool(
        conninfo=url,
        connection_class=psycopg.Connection[DictRow],
        kwargs=gated,
        **options,
    )
