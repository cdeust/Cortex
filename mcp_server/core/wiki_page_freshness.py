"""Freshness of a memory-derived wiki page, read from its source trace.

source: issue #715 (slice 2, acceptance criterion 3).

A page written with ``wiki_write(memory_ids=...)`` rests on the memories it
cites. ``cited_memory_sources`` already marks each cited memory the store no
longer resolves (``missing``), retired since (``stale``) or corrected by a
newer memory (``superseded_by_id``). This module folds those marks into one
verdict for the page and names its source frontier, so a caller learns
whether the synthesis still matches its sources without reading every entry,
and keeps that verdict when the trace itself is cut to fit the response.

Two states only. ``pending``: at least one cited memory changed since the
page cited it, so the page waits for a refresh. ``current``: every recorded
citation still resolves to a live, uncorrected memory. A ``failed`` state
needs a recorded refresh outcome; no such record exists before the persisted
frontier of acceptance criterion 2, so it is not reported here rather than
guessed.

The verdict covers the citations the store still records. A hard ``forget``
erases the citation row with the memory (``forget`` returns the pages in
``cited_by_pages``), so that page is not marked pending by this module;
criterion 1 of the issue covers it.

Pure: no I/O.
"""

from __future__ import annotations

from typing import Any

# source: issue #715, acceptance criterion 3 ("pending/failed/current state")
PAGE_CURRENT = "current"
# source: issue #715, acceptance criterion 3 ("pending/failed/current state")
PAGE_PENDING = "pending"


def _changed_since_cited(ref: dict[str, Any]) -> bool:
    return bool(ref.get("missing") or ref.get("stale")) or (
        ref.get("superseded_by_id") is not None
    )


def page_freshness(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """The page's freshness verdict and source frontier.

    precondition: ``sources`` is the full ``cited_memory_sources`` output for
    the page, before any cut to fit the response budget.
    postcondition: ``state`` is ``pending`` when at least one entry is
    missing, stale or superseded, else ``current``; ``pending_memory_ids``
    lists those entries in citation order; ``frontier`` gives the number of
    cited memories and the highest cited memory id (None when the page cites
    none). A page that cites nothing is ``current``: nothing it rests on has
    changed.
    """
    pending = [int(ref["memory_id"]) for ref in sources if _changed_since_cited(ref)]
    ids = [int(ref["memory_id"]) for ref in sources]
    return {
        "state": PAGE_PENDING if pending else PAGE_CURRENT,
        "pending_memory_ids": pending,
        "frontier": {
            "cited_memories": len(ids),
            "max_memory_id": max(ids) if ids else None,
        },
    }
