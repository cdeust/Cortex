"""Unit tests for the batch_pool capability guard (#636).

source: ADR-1089
"""

from __future__ import annotations

from mcp_server.handlers.consolidation.batch_pool_capability import (
    batch_pool_skip_reason,
)


class _NoBatchPool:
    """Stand-in for SqliteMemoryStore: no ``batch_pool`` attribute at all."""


class _WithBatchPool:
    """Stand-in for PgMemoryStore: ``batch_pool`` resolves to something."""

    batch_pool = object()


def test_skip_reason_present_when_store_lacks_batch_pool() -> None:
    reason = batch_pool_skip_reason(_NoBatchPool())
    assert reason is not None
    assert "batch_pool" in reason


def test_skip_reason_none_when_store_has_batch_pool() -> None:
    assert batch_pool_skip_reason(_WithBatchPool()) is None
