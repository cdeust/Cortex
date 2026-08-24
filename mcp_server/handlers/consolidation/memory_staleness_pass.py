"""Bounded file-existence staleness re-validation pass (fleet-watch #110).

``is_stale`` is the signal the injection banners now surface (age · grade ·
stale), but it only ever got *set* on file grounds by the manual
``validate_memory`` tool — so a memory referencing a file that was moved or
deleted stayed ``is_stale=FALSE`` until someone ran the tool by hand.
harness-comparison rev.2 measured exactly this: Harness B served facts months
stale with no stale flag.

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

Composition root: pure decision (``assess_staleness``) + an injected filesystem
resolver + store I/O. Script-invoked (``scripts/memory_staleness_revalidate.py``),
bounded per run, NOT on the commit critical path or the hot consolidate cycle.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Protocol

from mcp_server.core.staleness import assess_staleness, extract_file_references

logger = logging.getLogger(__name__)

# Per-run scan cap — bounds one run's FS+DB cost; mirrors the backfill passes'
# DEFAULT_*_LIMIT rationale (memory_domain_backfill_pass.py). A run that hits the
# cap resumes from the id cursor on the next invocation.
DEFAULT_STALENESS_SCAN_LIMIT = 5000
# Page size for the id-cursor scan.
# source: get_all_memories_for_validation default page (pg_store_queries.py:94)
#   is 1000; reused here for parity with the existing validation read path.
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
