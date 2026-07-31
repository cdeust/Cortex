"""Typed host contract + materialized cursor for the PostgreSQL store mixins.

``PgMemoryStore`` is assembled from eight persistence mixins, each of which
calls back into shared machinery the composed class provides (``_execute``,
``_conn``, ``batch_pool``). Before this module existed that contract was
implicit — every mixin accessed ``self._execute`` with no declaration, so the
type checker could not verify a single call against the real signature, and a
wrong call (or a renamed host method) surfaced at runtime instead of in CI.

``PgStoreHost`` makes the contract explicit: mixins inherit it, the
declarations live under ``TYPE_CHECKING`` so the class is empty at runtime
(zero MRO behavior change), and ``PgMemoryStore`` remains the sole runtime
implementer. This is the DIP form §5.1 of the coding standard asks for: the
mixins (consumers) name the abstraction they need; the store supplies it.

``MaterializedCursor`` lives here (moved from ``pg_store.py``) so both the
host contract and the store can name the concrete return type of ``_execute``
without an import cycle. Its rows are ``DictRow`` — every connection this
backend opens uses ``row_factory=dict_row`` — which is what lets the type
checker verify ``row["column"]`` access in the mixins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

# This module is reachable by import from the SQLite-default install (hooks ->
# injection_receipts -> pg_store_receipts -> here), and psycopg ships only in
# the optional [postgresql] extra. A module-scope `import psycopg` therefore
# made `import mcp_server.hooks.session_lifecycle` raise ModuleNotFoundError on
# every launch surface in PRIVACY.md lines 26-38. Only ProgrammingError is
# needed at RUNTIME (the rest are annotations, stringified by
# `from __future__ import annotations`), so the PG-only paths that raise it are
# unreachable without psycopg and the stand-in below is never matched.
# Surfaced by #220 broadening the SQLite CI job to the full suite.
_ProgrammingError: type[Exception]
try:  # PostgreSQL backend — the optional [postgresql] extra is installed.
    from psycopg import ProgrammingError as _PsycopgProgrammingError

    _ProgrammingError = _PsycopgProgrammingError
except ModuleNotFoundError:  # SQLite-default install — no psycopg present.

    class _MissingPsycopgProgrammingError(Exception):
        """Stand-in so this module imports without the [postgresql] extra."""

    _ProgrammingError = _MissingPsycopgProgrammingError


if TYPE_CHECKING:
    import psycopg
    from psycopg import sql
    from psycopg.rows import DictRow
    from psycopg_pool import ConnectionPool


class MaterializedCursor:
    """Lightweight cursor surrogate that pre-fetches rows.

    Phase 5: connections are checked out from the pool per query and
    returned at the end of ``_execute``. The original ``psycopg.Cursor``
    becomes unusable once the connection is returned to the pool, so we
    eagerly read all rows into memory here and expose the subset of the
    Cursor API that production code actually uses: ``fetchone``,
    ``fetchall``, and ``rowcount``.
    """

    __slots__ = ("_rows", "_idx", "_rowcount")

    def __init__(self, cursor: psycopg.Cursor[DictRow]) -> None:
        self._rowcount = cursor.rowcount
        try:
            self._rows: list[DictRow] = cursor.fetchall()
        except (_ProgrammingError, TypeError):
            # DDL / DML statements without a result set — fetchall raises.
            self._rows = []
        self._idx = 0

    def fetchone(self) -> DictRow | None:
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return row

    def one(self) -> DictRow:
        """Return the next row, raising when the statement produced none.

        For statements whose contract guarantees a row (``INSERT ...
        RETURNING``, aggregate ``SELECT count(*)``). A missing row there
        means the database broke its side of the contract, so this raises
        immediately with the real cause instead of letting the caller fail
        later on a ``None`` with no context.
        """
        row = self.fetchone()
        if row is None:
            raise _ProgrammingError(  # noqa: TRY003 — one-off message, not reused (§3.3)
                "statement guaranteed a row (RETURNING/aggregate) but produced none"
            )
        return row

    def fetchall(self) -> list[DictRow]:
        remaining = self._rows[self._idx :]
        self._idx = len(self._rows)
        return remaining

    @property
    def rowcount(self) -> int:
        return self._rowcount

    def __iter__(self) -> Iterator[DictRow]:
        while (row := self.fetchone()) is not None:
            yield row


class PgStoreHost:
    """Static contract every ``Pg*Mixin`` relies on.

    Declaration-only: the ``TYPE_CHECKING`` guard keeps the class empty at
    runtime, so inheriting it changes no MRO lookup and adds no behavior.
    ``PgMemoryStore`` provides every member listed here.
    """

    if TYPE_CHECKING:
        _conn: psycopg.Connection[DictRow]

        @property
        def batch_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]: ...

        def _execute(
            self,
            query: str | sql.Composable,
            params: Any = None,
            **kwargs: Any,
        ) -> MaterializedCursor: ...

        def _normalize_memory_row(self, row: dict[str, Any]) -> dict[str, Any]: ...
