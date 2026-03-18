"""Sensory buffer — working memory for immediate context (pre-consolidation).

Implements a bounded ring buffer for transient content that arrives too fast
to individually gate through the write gate. Content accumulates here during
a session, then is drained to long-term memory on:
  - Explicit drain() call (e.g., at session end)
  - Buffer fill (oldest items displaced)
  - Importance threshold crossing (item is too important to delay)

Analogous to the hippocampal fast-binding system in neuroscience —
it holds recent experiences before they're consolidated into cortex.

Pure business logic — no I/O. All state is in-process (not persisted).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mcp_server.core import thermodynamics


# ── Buffer item ───────────────────────────────────────────────────────────


@dataclass
class BufferItem:
    """A single item in the sensory buffer."""

    content: str
    tags: list[str]
    source: str
    directory: str
    domain: str
    importance: float
    valence: float
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tags": self.tags,
            "source": self.source,
            "directory": self.directory,
            "domain": self.domain,
            "importance": self.importance,
            "valence": self.valence,
            "created_at": self.created_at,
        }


# ── Sensory buffer ────────────────────────────────────────────────────────


class SensoryBuffer:
    """Bounded working memory buffer.

    Items are held here until they are consolidated into long-term memory
    via drain() or forced out by importance threshold.

    Parameters
    ----------
    capacity : int
        Maximum number of items before oldest are displaced.
    importance_threshold : float
        Items at or above this importance score bypass the buffer and are
        flagged for immediate consolidation (is_urgent=True).
    """

    def __init__(
        self,
        capacity: int = 50,
        importance_threshold: float = 0.7,
    ) -> None:
        self._buffer: deque[BufferItem] = deque(maxlen=capacity)
        self._capacity = capacity
        self._importance_threshold = importance_threshold
        self._displaced: list[BufferItem] = []  # Items evicted by maxlen

    # ── Write ──────────────────────────────────────────────────────────

    def _append_with_displacement(self, item: BufferItem) -> None:
        """Append item to buffer, tracking any displaced item."""
        if len(self._buffer) >= self._capacity:
            self._displaced.append(self._buffer[0])
        self._buffer.append(item)

    def push(
        self,
        content: str,
        *,
        tags: list[str] | None = None,
        source: str = "buffer",
        directory: str = "",
        domain: str = "",
    ) -> dict[str, Any]:
        """Add an item to the buffer, computing importance and valence automatically."""
        importance = thermodynamics.compute_importance(content, tags or [])
        valence = thermodynamics.compute_valence(content)

        item = BufferItem(
            content=content,
            tags=tags or [],
            source=source,
            directory=directory,
            domain=domain,
            importance=importance,
            valence=valence,
        )

        is_urgent = importance >= self._importance_threshold
        if not is_urgent:
            self._append_with_displacement(item)

        return {
            "buffered": not is_urgent,
            "is_urgent": is_urgent,
            "importance": round(importance, 4),
            "valence": round(valence, 4),
            "buffer_size": len(self._buffer),
            "item": item.to_dict() if is_urgent else None,
        }

    # ── Read ───────────────────────────────────────────────────────────

    def peek(self, n: int = 5) -> list[BufferItem]:
        """Return the n most-recently-added items without removing them."""
        items = list(self._buffer)
        return items[-n:]

    def peek_important(self, threshold: float | None = None) -> list[BufferItem]:
        """Return items above an importance threshold without removing them."""
        thresh = (
            threshold if threshold is not None else self._importance_threshold * 0.8
        )
        return [item for item in self._buffer if item.importance >= thresh]

    # ── Drain ──────────────────────────────────────────────────────────

    def drain(
        self,
        min_importance: float = 0.0,
        max_items: int | None = None,
    ) -> list[BufferItem]:
        """Drain items from the buffer for consolidation into long-term memory.

        Items are removed from the buffer as they are drained.

        Args:
            min_importance: Only drain items at or above this importance.
            max_items: Maximum items to drain (None = all qualifying items).

        Returns:
            List of drained BufferItems, most-important first.
        """
        all_items = list(self._buffer)
        qualifying = [item for item in all_items if item.importance >= min_importance]
        qualifying.sort(key=lambda x: x.importance, reverse=True)

        if max_items is not None:
            qualifying = qualifying[:max_items]

        # Remove drained items from buffer
        drained_set = set(id(item) for item in qualifying)
        remaining = deque(
            (item for item in self._buffer if id(item) not in drained_set),
            maxlen=self._capacity,
        )
        self._buffer = remaining

        return qualifying

    def drain_displaced(self) -> list[BufferItem]:
        """Return and clear items that were evicted due to buffer overflow."""
        evicted = list(self._displaced)
        self._displaced.clear()
        return evicted

    def drain_all(self) -> list[BufferItem]:
        """Drain everything, sorted by importance descending."""
        all_items = sorted(self._buffer, key=lambda x: x.importance, reverse=True)
        self._buffer.clear()
        return all_items

    # ── Stats ──────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        return len(self._buffer)

    @property
    def is_full(self) -> bool:
        return len(self._buffer) >= self._capacity

    @property
    def capacity(self) -> int:
        return self._capacity

    def stats(self) -> dict[str, Any]:
        """Return buffer statistics."""
        items = list(self._buffer)
        importances = [item.importance for item in items]
        return {
            "size": len(items),
            "capacity": self._capacity,
            "fill_pct": round(len(items) / self._capacity * 100, 1)
            if self._capacity
            else 0,
            "avg_importance": round(sum(importances) / len(importances), 4)
            if importances
            else 0.0,
            "max_importance": round(max(importances), 4) if importances else 0.0,
            "displaced_pending": len(self._displaced),
            "sources": list({item.source for item in items}),
        }


# ── Module-level singleton ────────────────────────────────────────────────
# Shared buffer for the current process lifetime.
# Handlers can import and use this directly.

_global_buffer: SensoryBuffer | None = None


def get_global_buffer(
    capacity: int = 50, importance_threshold: float = 0.7
) -> SensoryBuffer:
    """Get or create the module-level shared sensory buffer."""
    global _global_buffer
    if _global_buffer is None:
        _global_buffer = SensoryBuffer(
            capacity=capacity,
            importance_threshold=importance_threshold,
        )
    return _global_buffer


def reset_global_buffer() -> None:
    """Reset the global buffer (useful for testing)."""
    global _global_buffer
    _global_buffer = None
