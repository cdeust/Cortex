"""Bounded file-existence staleness re-validation pass (fleet-watch #110).

This pass makes the flag fire automatically: it pages non-stale,
file-referencing memories, re-checks whether their referenced paths still
exist, and marks ``is_stale`` via the same pure assessment
(``core.staleness.assess_staleness``) and store method (``mark_memory_stale``)
the tool uses.

Deliberately **mark-only**: it never de-stales (rehabilitates) a memory. The
active-forgetting circuit (``consolidation/forgetting.py``, Rac1) also writes
``is_stale`` for non-file reasons; auto-rehabilitation here could fight it, so
de-staling stays with the explicit, human-invoked ``validate_memory`` tool.
Existence only — content-change detection (a file that still exists but diverged
from what the memory claims) needs per-ref content hashing and is a separate
#110 seam.

source: ADR-0369"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from mcp_server.core.staleness import assess_staleness, extract_file_references

logger = logging.getLogger(__name__)

# source: ADR-0369
DEFAULT_STALENESS_SCAN_LIMIT = 5000
# source: ADR-0369
_PAGE = 1000

ResolveExistingFn = Callable[[list[str], str], set[str]]


class _StaleStore(Protocol):
    def get_all_memories_for_validation(
        self, limit: int, *, after_id: int, include_stale: bool
    ) -> list[dict[str, Any]]: ...

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None: ...


def _mark_if_missing(
    store: _StaleStore,
    mem: dict,
    resolve_existing: ResolveExistingFn,
    threshold: float,
) -> bool:
    """Mark one memory stale if its file refs no longer resolve.

    Skips memories with no file refs (their staleness, if any, is not
    file-derived) and already-stale rows (idempotent). Returns True if it
    marked the memory stale this call.
    """
    content = mem.get("content", "")
    refs = extract_file_references(content)
    if not refs or mem.get("is_stale"):
        return False
    existing = resolve_existing(refs, mem.get("directory_context", "") or "")
    report = assess_staleness(
        mem["id"], content, existing_paths=existing, threshold=threshold
    )
    if report.is_stale:
        store.mark_memory_stale(mem["id"], True)
        return True
    return False


def revalidate_staleness(
    store: _StaleStore,
    resolve_existing: ResolveExistingFn,
    *,
    limit: int = DEFAULT_STALENESS_SCAN_LIMIT,
    threshold: float = 0.5,
) -> dict[str, int]:
    """Page non-stale, file-referencing memories and set is_stale on missing refs."""
    counts = {"scanned": 0, "marked_stale": 0}
    after_id = 0
    while counts["scanned"] < limit:
        page = store.get_all_memories_for_validation(
            limit=min(_PAGE, limit - counts["scanned"]),
            after_id=after_id,
            include_stale=False,
        )
        if not page:
            break
        for mem in page:
            after_id = max(after_id, int(mem["id"]))
            counts["scanned"] += 1
            if _mark_if_missing(store, mem, resolve_existing, threshold):
                counts["marked_stale"] += 1
        if len(page) < _PAGE:
            break
    logger.info("staleness revalidation: %s", counts)
    return counts
