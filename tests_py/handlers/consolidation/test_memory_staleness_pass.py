"""Unit tests for the file-existence staleness re-validation pass (#110).

DB-free: a fake store records mark_memory_stale calls and an injected resolver
stands in for the filesystem. Verifies the mark-only, skip-no-refs,
skip-already-stale, and cursor-paging behavior.
"""

from __future__ import annotations

from typing import Any

from mcp_server.handlers.consolidation.memory_staleness_pass import (
    revalidate_staleness,
)


class _FakeStore:
    def __init__(self, memories: list[dict]):
        self._mems = memories
        self.marked: list[tuple[int, bool]] = []

    def get_all_memories_for_validation(
        self, limit: int, *, after_id: int, include_stale: bool
    ) -> list[dict[str, Any]]:
        rows = [
            m
            for m in self._mems
            if m["id"] > after_id and (include_stale or not m.get("is_stale"))
        ]
        rows.sort(key=lambda m: m["id"])
        return rows[:limit]

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        self.marked.append((memory_id, stale))
        for m in self._mems:
            if m["id"] == memory_id:
                m["is_stale"] = stale


def _resolve(refs: list[str], _base: str) -> set[str]:
    # Everything resolves except paths that mention "gone".
    return {r for r in refs if "gone" not in r}


def test_marks_only_memory_with_missing_ref() -> None:
    memories = [
        {"id": 1, "content": "see src/here.py and src/gone.py", "is_stale": False},
        {"id": 2, "content": "see src/here.py", "is_stale": False},
        {"id": 3, "content": "prose with no file references at all", "is_stale": False},
        {"id": 4, "content": "see src/gone.py", "is_stale": True},  # already stale
    ]
    store = _FakeStore(memories)

    counts = revalidate_staleness(store, _resolve, threshold=0.5)

    # Only memory 1 (a missing ref) is newly marked; 2 resolves, 3 has no refs,
    # 4 is already stale (excluded by include_stale=False).
    assert store.marked == [(1, True)]
    assert counts["marked_stale"] == 1
    assert counts["scanned"] == 3


def test_never_destales() -> None:
    # A memory whose refs all resolve is left untouched — no de-stale write,
    # so the pass can never fight the active-forgetting circuit.
    memories = [{"id": 1, "content": "see src/here.py", "is_stale": False}]
    store = _FakeStore(memories)
    revalidate_staleness(store, _resolve)
    assert store.marked == []


def test_respects_scan_limit() -> None:
    memories = [
        {"id": i, "content": "see src/gone.py", "is_stale": False} for i in range(1, 11)
    ]
    store = _FakeStore(memories)
    counts = revalidate_staleness(store, _resolve, limit=4)
    assert counts["scanned"] == 4
    assert counts["marked_stale"] == 4
