"""source: ADR-0550"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

# source: ADR-0550
_ProgrammingError: type[Exception]
try:  # PostgreSQL backend — the optional [postgresql] extra is installed.
    from psycopg import ProgrammingError as _PsycopgProgrammingError

    _ProgrammingError = _PsycopgProgrammingError
except ModuleNotFoundError:  # SQLite-default install — no psycopg present.

    class _MissingPsycopgProgrammingError(Exception):
        """Stand-in so this module imports without the [postgresql] extra."""

    _ProgrammingError = _MissingPsycopgProgrammingError


if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    import psycopg
    from psycopg import sql
    from psycopg.rows import DictRow
    from psycopg_pool import ConnectionPool


class MaterializedCursor:
    """Lightweight cursor surrogate that pre-fetches rows.

    source: ADR-0550"""

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

        source: ADR-0550"""
        row = self.fetchone()
        if row is None:
            raise _ProgrammingError(
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
    """Describe the connection and methods required by PostgreSQL store mixins.

    source: ADR-0550"""

    if TYPE_CHECKING:
        _conn: psycopg.Connection[DictRow]
        _url: str
        _interactive_pool: ConnectionPool[psycopg.Connection[DictRow]] | None
        _batch_pool: ConnectionPool[psycopg.Connection[DictRow]] | None

        @property
        def batch_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]: ...

        @property
        def interactive_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]: ...

        def acquire_interactive(
            self,
        ) -> AbstractContextManager[psycopg.Connection[DictRow]]: ...

        def _execute(
            self,
            query: str | sql.Composable,
            params: Any = None,
            **kwargs: Any,
        ) -> MaterializedCursor: ...

        def _normalize_memory_row(self, row: dict[str, Any]) -> dict[str, Any]: ...

        @staticmethod
        def _isoformat_datetime_fields(d: dict[str, Any]) -> dict[str, Any]: ...

        @staticmethod
        def _bytes_to_vector(emb: bytes | None) -> Any: ...

        @staticmethod
        def _vector_to_bytes(vec: Any) -> bytes | None: ...

        def _insert_memory_on(
            self, conn: psycopg.Connection[DictRow], data: dict[str, Any]
        ) -> int: ...

        def get_all_memories_for_decay(self) -> list[dict[str, Any]]: ...
