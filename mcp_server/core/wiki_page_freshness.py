"""Freshness of a memory-derived wiki page, read from its source trace.

source: issue #715 (slice 2, acceptance criterion 3).

A page written with ``wiki_write(memory_ids=...)`` rests on the memories it
cites. ``cited_memory_sources`` already marks each cited memory the store no
longer resolves (``missing``), retired since (``stale``) or corrected by a
newer memory (``superseded_by_id``). This module folds those marks into one
verdict for the page and names its source frontier, so a caller learns
whether the synthesis still matches its sources without reading every entry,
and keeps that verdict when the trace itself is cut to fit the response.

Three states. ``failed``: the page cites memories, but its text on disk is
not the text its citations were recorded with (the ``wiki.pages`` body hash
differs), so its last refresh did not record its sources: a ``wiki_write``
whose citation unit was interrupted (``citations_interrupted``, issue #715
slice 3) keeps the new text on disk and the previous record, or the page was
rewritten by a path that does not record citations. The recorded frontier
then describes another text, so ``failed`` wins over the two other states.
``pending``: at least one cited memory changed since the page cited it, so
the page waits for a refresh. ``current``: every recorded citation still
resolves to a live, uncorrected memory.

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
# source: issue #715, acceptance criterion 3 ("pending/failed/current state")
PAGE_FAILED = "failed"


def _changed_since_cited(ref: dict[str, Any]) -> bool:
    return bool(ref.get("missing") or ref.get("stale")) or (
        ref.get("superseded_by_id") is not None
    )


def _state(pending: list[int], cites: bool, record_matches_text: bool) -> str:
    if cites and not record_matches_text:
        return PAGE_FAILED
    return PAGE_PENDING if pending else PAGE_CURRENT


def page_freshness(
    sources: list[dict[str, Any]], *, record_matches_text: bool
) -> dict[str, Any]:
    """The page's freshness verdict and source frontier.

    precondition: ``sources`` is the full ``cited_memory_sources`` output for
    the page, before any cut to fit the response budget;
    ``record_matches_text`` says whether the page's recorded body hash is the
    hash of the body now on disk.
    postcondition: ``state`` is ``failed`` when the page cites at least one
    memory and its record does not match its text, else ``pending`` when at
    least one entry is missing, stale or superseded, else ``current``;
    ``record_matches_text`` is echoed; ``pending_memory_ids``
    lists those entries in citation order; ``frontier`` gives the number of
    cited memories and the highest cited memory id (None when the page cites
    none). A page that cites nothing is ``current``: nothing it rests on has
    changed, whatever its record says.
    """
    pending = [int(ref["memory_id"]) for ref in sources if _changed_since_cited(ref)]
    ids = [int(ref["memory_id"]) for ref in sources]
    return {
        "state": _state(pending, bool(ids), record_matches_text),
        "record_matches_text": record_matches_text,
        "pending_memory_ids": pending,
        "frontier": {
            "cited_memories": len(ids),
            "max_memory_id": max(ids) if ids else None,
        },
    }
