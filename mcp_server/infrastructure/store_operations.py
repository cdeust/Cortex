"""Named database operations: the one way code outside the store reaches a
connection (ADR-1112 increment 2).

A store operation is a module-level function in ``mcp_server.infrastructure``
whose first parameter is a database connection, marked with
``@store_operation``. Callers never hold a connection: they ask the store,
``store.call(fn, *args, pool=...)``, and the store lends one connection for
that one call. In process, the call runs on the store's own pool; through the
broker (increments 3 to 5), the store sends the operation's name and its
arguments and the broker resolves the name with ``resolve_operation``, which
accepts only marked functions of ``mcp_server.infrastructure`` modules. No SQL
text, and no connection, ever crosses a process boundary.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import contextvars
import functools
import importlib
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from typing import Any, Literal, TypeVar

# source: ADR-1112 the only package whose functions may be resolved by name
ALLOWED_PACKAGE = "mcp_server.infrastructure."
# source: ADR-1112 the marker attribute set by the decorator
_MARK = "__cortex_store_operation__"

Pool = Literal["interactive", "batch"]
RequestClass = Literal["interactive", "background"]
F = TypeVar("F", bound=Callable[..., Any])
R = TypeVar("R")
_request_class: contextvars.ContextVar[RequestClass] = contextvars.ContextVar(
    "cortex_store_request_class", default="interactive"
)


def current_request_class() -> RequestClass:
    """The class of the store work running in this context (ADR-1112
    decision 4): background work (consolidation, backfill, ingest) runs on
    the batch pool and, through the broker, in the background queue."""
    return _request_class.get()


@contextmanager
def request_class(value: RequestClass) -> Iterator[None]:
    token = _request_class.set(value)
    try:
        yield
    finally:
        _request_class.reset(token)


def background_work(
    handler: Callable[..., Coroutine[Any, Any, R]],
) -> Callable[..., Coroutine[Any, Any, R]]:
    """Run an async tool handler's store work as background requests."""

    @functools.wraps(handler)
    async def run(*args: Any, **kwargs: Any) -> R:
        with request_class("background"):
            return await handler(*args, **kwargs)

    return run


def default_pool() -> Pool:
    return "batch" if current_request_class() == "background" else "interactive"


class UnknownOperationError(LookupError):
    """The name does not designate a marked operation; nothing was run."""


def store_operation(fn: F) -> F:
    """Mark ``fn(conn, ...)`` as callable through ``store.call``."""
    if not fn.__module__.startswith(ALLOWED_PACKAGE):
        raise ValueError(f"store operations live in {ALLOWED_PACKAGE}*")
    setattr(fn, _MARK, True)
    return fn


def is_store_operation(fn: object) -> bool:
    return bool(getattr(fn, _MARK, False))


def operation_name(fn: Callable[..., Any]) -> str:
    """``module:qualname``, the wire name of a marked operation."""
    if not is_store_operation(fn):
        raise UnknownOperationError(f"{fn!r} is not a store operation")
    return f"{fn.__module__}:{fn.__qualname__}"


def resolve_operation(name: str) -> Callable[..., Any]:
    """The marked function a wire name designates, or ``UnknownOperationError``."""
    module_name, _, qualname = name.partition(":")
    if not module_name.startswith(ALLOWED_PACKAGE) or not qualname or "." in qualname:
        raise UnknownOperationError(f"not an operation name: {name!r}")
    try:
        fn = getattr(importlib.import_module(module_name), qualname)
    except (ImportError, AttributeError) as exc:
        raise UnknownOperationError(f"no such operation: {name!r}") from exc
    if not is_store_operation(fn):
        raise UnknownOperationError(f"not a marked operation: {name!r}")
    return fn


class StoreOperationsMixin:
    """``call`` for stores that lend connections with ``acquire_*``."""

    def call(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        pool: Pool | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run one marked operation on one borrowed connection; return its
        (fully materialised) result. Without ``pool``, background work runs
        on the batch pool and everything else on the interactive pool."""
        if not is_store_operation(fn):
            raise UnknownOperationError(f"{fn!r} is not a store operation")
        chosen = pool or default_pool()
        acquire = getattr(
            self, "acquire_batch" if chosen == "batch" else "acquire_interactive"
        )
        with acquire() as conn:
            # One operation is one unit of work: PostgreSQL pool connections
            # are in autocommit (commit and rollback are no-ops there);
            # SQLite's compat connection is not.
            try:
                result = fn(conn, *args, **kwargs)
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
            return result

    def call_batch(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """``call`` on the batch pool: background work (consolidation passes,
        backfills, ingest), so it never competes with interactive calls."""
        return self.call(fn, *args, pool="batch", **kwargs)
