"""Give a fake store the real store-operation funnel.

Production stores inherit ``StoreOperationsMixin`` (ADR-1112 increment 2):
``store.call(op, ...)`` borrows a connection from ``acquire_interactive`` or
``acquire_batch``, runs the marked operation on it, commits, and rolls back
on error. A test fake that only supplies ``acquire_*`` gets the same
``call``/``call_batch`` here, so the operation's real SQL and the real
commit/rollback discipline still run against the fake connection.
"""

from __future__ import annotations

import contextlib
import functools
from collections.abc import Iterator
from typing import Any

from mcp_server.infrastructure.store_operations import StoreOperationsMixin


def bind_store_calls(store: Any, backend: str | None = None) -> Any:
    """Attach the mixin's ``call``/``call_batch`` to ``store``; return it."""
    store.call = functools.partial(StoreOperationsMixin.call, store)
    store.call_batch = functools.partial(StoreOperationsMixin.call_batch, store)
    if backend is not None:
        store.backend = backend
    return store


def mark_test_operation(fn: Any) -> Any:
    """Mark a test double that replaces a marked operation (monkeypatched in
    place of one), so in-process ``store.call`` accepts it. Wire resolution
    (``resolve_operation``) still refuses it: it lives outside
    ``mcp_server.infrastructure``."""
    from mcp_server.infrastructure import store_operations  # noqa: PLC0415

    try:
        setattr(fn, store_operations._MARK, True)  # noqa: SLF001 — test double only
    except AttributeError:  # a bound method: mark a forwarding function instead

        def forward(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        setattr(forward, store_operations._MARK, True)  # noqa: SLF001 — test double only
        return forward
    return fn


class FakeConn:
    """A connection double that counts commits and rollbacks."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeConnStore(StoreOperationsMixin):
    """A store that lends one connection double (``conn``) on both pools,
    with the real ``call``/``call_batch``."""

    def __init__(self, conn: Any = None, backend: str = "postgresql") -> None:
        self.conn = conn if conn is not None else FakeConn()
        self.backend = backend

    @contextlib.contextmanager
    def acquire_interactive(self) -> Iterator[Any]:
        yield self.conn

    @contextlib.contextmanager
    def acquire_batch(self) -> Iterator[Any]:
        yield self.conn
