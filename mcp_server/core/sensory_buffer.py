"""Sensory buffer — working memory for immediate context (pre-consolidation).

source: ADR-0252"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from mcp_server.core import thermodynamics
from mcp_server.core.attentional_control import (
    FOCUS_CAPACITY_DEFAULT,
    ATTENTION_TEMPERATURE,
    allocate_attention,
)

if TYPE_CHECKING:
    from mcp_server.core.attentional_control import AttentionAllocation

# ── Buffer item ───────────────────────────────────────────────────────────


@dataclass
class BufferItem:
    """A single item in the sensory buffer.

    source: ADR-0252"""

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


def buffer_item_to_dict(item: BufferItem) -> dict[str, Any]:
    return {
        "content": item.content,
        "tags": item.tags,
        "source": item.source,
        "directory": item.directory,
        "domain": item.domain,
        "importance": item.importance,
        "valence": item.valence,
        "created_at": item.created_at,
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
            "item": buffer_item_to_dict(item) if is_urgent else None,
        }

    # ── Read ───────────────────────────────────────────────────────────

    def peek(self, n: int = 5) -> list[BufferItem]:
        """Return the n most-recently-added items without removing them."""
        items = list(self._buffer)
        return items[-n:]

    def focus(
        self,
        query: str,
        *,
        capacity: int | None = None,
        temperature: float | None = None,
    ) -> "AttentionAllocation":
        """Direct the attentional spotlight (A1) over the buffered items.

        source: ADR-0252

        Returns an ``AttentionAllocation`` whose ``focus`` items are dicts (the
        BufferItem payload plus an ``attention_weight``). An empty buffer yields
        an empty allocation.
        """

        items = [buffer_item_to_dict(item) for item in self._buffer]
        return allocate_attention(
            query,
            items,
            capacity=capacity if capacity is not None else FOCUS_CAPACITY_DEFAULT,
            temperature=(
                temperature if temperature is not None else ATTENTION_TEMPERATURE
            ),
        )

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
