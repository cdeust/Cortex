"""Backend transaction finalization at the MCP handler boundary."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mcp_server.infrastructure.sqlite_request_scope import (
    sqlite_request_scope,
)


@contextmanager
def handler_transaction_scope() -> Iterator[None]:
    """Reject or roll back unfinished SQLite work at the handler boundary."""
    with sqlite_request_scope():
        yield
