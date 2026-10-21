"""What a broker request may run: allowlisted store methods and marked
store operations, nothing else.

The method allowlist is the store's public interface minus what only makes
sense in process (connection lending, closing, generators: a stream is a
sequence of stateless page requests, see ``PAGE_METHODS``), plus the keyset
page readers those streams use. Operations are resolved by name through
``store_operations.resolve_operation`` (marked functions of
``mcp_server.infrastructure`` only). A request of the background class runs
its store work on the batch pool (``store_operations.request_class``).

source: ADR-1112 decision 3
"""

from __future__ import annotations

import inspect
from typing import Any

from mcp_server.infrastructure.store_operations import (
    UnknownOperationError,
    resolve_operation,
)
from mcp_server.infrastructure.store_operations import (
    request_class as store_request_class,
)

# source: ADR-1112 in-process only: connection lending, lifecycle, generators
_EXCLUDED = frozenset(
    {"acquire_batch", "acquire_interactive", "close", "call", "call_batch"}
)
# source: ADR-1112 the keyset page behind iter_memories_for_decay (increment 0)
PAGE_METHODS = frozenset({"_fetch_decay_page"})


def allowed_methods(store_class: type) -> frozenset[str]:
    names = {
        name
        for name, member in inspect.getmembers(store_class, callable)
        if not name.startswith("_")
        and not name.startswith("iter_")
        and name not in _EXCLUDED
        and not isinstance(member, type)
    }
    return frozenset(names) | PAGE_METHODS


class StoreExecutor:
    """Runs one request on the broker's store."""

    def __init__(self, store: Any) -> None:
        self.store = store
        self.methods = allowed_methods(type(store))

    def __call__(
        self, kind: str, name: str, args: list, kwargs: dict, request_class: str
    ) -> Any:
        with store_request_class(
            "background" if request_class == "background" else "interactive"
        ):
            if kind == "method":
                if name not in self.methods:
                    raise UnknownOperationError(f"not a broker method: {name!r}")
                return getattr(self.store, name)(*args, **kwargs)
            return self.store.call(resolve_operation(name), *args, **kwargs)
