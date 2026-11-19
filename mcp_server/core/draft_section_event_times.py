"""A refined draft section keeps the event time of each claim it cites (#717).

source: issue #717 (slice 8: "wiki_refine keeps event_times through a rewrite");
decision of 19 November 2026 on #717, option (a): the page carries no date of
its own, each section names per claim the ``event_time`` its row stores.

``wiki_synthesize`` writes ``Section.event_times`` (claim id -> stored
EventTime). ``wiki_refine_draft`` replaces the sections with the prose the
caller sends, which names ``heading``, ``body`` and ``claim_ids`` and no time:
written as sent, the rewrite dropped every event time of the draft. The times
are the server's record of what each claim's sentence stated, so they are
carried from the draft being refined, keyed by claim id, wherever the caller
moves the claim. A time the caller sends is not read: a refinement rewrites
prose, it does not state dates. A cited claim the draft holds no time for
gets none, as nothing here can say what its sentence stated (a draft written
before slice 6 holds no ``event_times``; ``wiki_synthesize`` with ``force``
writes them).
"""

from __future__ import annotations

from typing import Any


def draft_event_times(sections: list[dict[str, Any]]) -> dict[int, Any]:
    """Claim id -> stored event time, over every section of a draft.

    JSON object keys are text, so ``"5"`` names claim 5. A claim is timed once
    by synthesis (one section per claim); were two sections to time it, they
    hold the same claim row's value.
    """
    times: dict[int, Any] = {}
    for section in sections:
        for claim_id, stored in (section.get("event_times") or {}).items():
            times[int(claim_id)] = stored
    return times


def _timed(claim_id: Any, times: dict[int, Any]) -> bool:
    """A claim id the draft times; ``True`` or ``"5"`` names no claim row."""
    return type(claim_id) is int and claim_id in times


def carry_event_times(
    refined: list[dict[str, Any]], stored: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The refined sections, each timing exactly the stored claims it cites."""
    times = draft_event_times(stored)
    carried: list[dict[str, Any]] = []
    for section in refined:
        cited = [cid for cid in section.get("claim_ids") or [] if _timed(cid, times)]
        # The caller's own "event_times", if any, is overwritten here.
        carried.append({**section, "event_times": {str(c): times[c] for c in cited}})
    return carried
