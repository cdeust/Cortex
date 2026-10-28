"""SQLite connection and cursor classes that route write parameters through
the redaction gate.

``sqlite_connection_registry`` opens every store connection with
``factory=GatedConnection``. ``Connection.execute``/``executemany`` and every
cursor the connection hands out (the compat layer's ``_CompatExecutingCursor``
and the ``_raw_conn.executemany`` call sites alike) are ``GatedCursor``s, so a
write statement cannot bind a parameter that has not been redacted, and a
script that writes (``executescript``, values inline) is redacted as text.

source: ADR-1110"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from mcp_server.shared.redaction_gate import (
    is_write_statement,
    redact_params,
    redact_script,
    redact_value,
)


class GatedCursor(sqlite3.Cursor):
    """A cursor whose write statements bind redacted parameters."""

    def execute(self, sql: str, parameters: Any = (), /) -> "GatedCursor":
        return super().execute(sql, redact_params(sql, parameters))

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Any], /
    ) -> "GatedCursor":
        if is_write_statement(sql):
            seq_of_parameters = (redact_value(p) for p in seq_of_parameters)
        return super().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script: str, /) -> "GatedCursor":
        super().executescript(redact_script(sql_script))
        return self


class GatedConnection(sqlite3.Connection):
    """A connection whose every cursor is a :class:`GatedCursor`."""

    def cursor(self, factory: Any = GatedCursor) -> Any:  # noqa: D102
        if not issubclass(factory, GatedCursor):
            raise TypeError("store connections only hand out gated cursors")
        return super().cursor(factory)

    def execute(self, sql: str, parameters: Any = (), /) -> GatedCursor:
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql: str, parameters: Iterable[Any], /) -> GatedCursor:
        return self.cursor().executemany(sql, parameters)

    def executescript(self, sql_script: str, /) -> GatedCursor:
        return self.cursor().executescript(sql_script)
