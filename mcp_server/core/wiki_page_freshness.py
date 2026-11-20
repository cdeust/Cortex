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

A hard ``forget`` erases the citation row with the memory (ADR-1111), so the
trace no longer names it; the page keeps a retraction instead, until its next
full write (``wiki.page_retractions``, issue #715 criterion 1). Each
retraction counts in ``retracted_sources`` and makes the page ``pending``,
even when no citation is left: the text may still say what the erased memory
said.

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


def _state(pending: bool, rests_on_sources: bool, record_matches_text: bool) -> str:
    if rests_on_sources and not record_matches_text:
        return PAGE_FAILED
    return PAGE_PENDING if pending else PAGE_CURRENT


def page_freshness(
    sources: list[dict[str, Any]],
    *,
    record_matches_text: bool,
    retracted_sources: int,
) -> dict[str, Any]:
    """The page's freshness verdict and source frontier.

    precondition: ``sources`` is the full ``cited_memory_sources`` output for
    the page, before any cut to fit the response budget;
    ``record_matches_text`` says whether the page's recorded hash is the
    hash of the whole page now on disk, frontmatter included;
    ``retracted_sources`` is the number of cited memories erased since the
    page's last full write.
    postcondition: ``state`` is ``failed`` when the page rests on sources
    (it cites at least one memory or has a retraction) and its record does
    not match its text, else ``pending`` when at least one entry is missing,
    stale or superseded or a retraction exists, else ``current``;
    ``record_matches_text`` and ``retracted_sources`` are echoed;
    ``pending_memory_ids`` lists the changed entries in citation order;
    ``frontier`` gives the number of cited memories and the highest cited
    memory id (None when the page cites none). A page that cites nothing
    and has no retraction is ``current``: nothing it rests on has changed,
    whatever its record says.
    """
    pending = [int(ref["memory_id"]) for ref in sources if _changed_since_cited(ref)]
    ids = [int(ref["memory_id"]) for ref in sources]
    retracted = retracted_sources > 0
    return {
        "state": _state(
            bool(pending) or retracted, bool(ids) or retracted, record_matches_text
        ),
        "record_matches_text": record_matches_text,
        "retracted_sources": retracted_sources,
        "pending_memory_ids": pending,
        "frontier": {
            "cited_memories": len(ids),
            "max_memory_id": max(ids) if ids else None,
        },
    }
