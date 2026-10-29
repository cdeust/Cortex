"""Exact replay operations exposed by each persistence backend (#707).

The normalized maintenance pass in memory_dedup_exact_pass remains separate.
source: PR #827 review 6470052457: atomic writes belong on the store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_server.infrastructure.memory_store import MemoryStore


def find_exact(store: MemoryStore, data: dict[str, Any]) -> int | None:
    """Read-only preflight; persistence repeats it under the write lock."""
    return store.find_exact_memory(data)


def insert_exact(store: MemoryStore, data: dict[str, Any]) -> tuple[int, bool]:
    """Return the existing id without enrichment when the write is a replay."""
    return store.insert_memory_exact(data)


def collapse_exact(store: MemoryStore) -> dict[str, int]:
    """Retain scoped duplicates and propagate their protection flags."""
    return store.collapse_exact_replays()
