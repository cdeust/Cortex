"""A refined draft keeps each claim's own event time (#717, slice 8).

``wiki_refine_draft`` replaced the sections with the caller's prose, which
names no time, so a rewrite dropped every ``event_times`` that
``wiki_synthesize`` wrote (slice 6). The pipeline under test is the real one,
through the handlers' composition root on the default SQLite backend:
extract, synthesise, then refine the draft as a caller would.
"""

from __future__ import annotations

import asyncio
import json

from mcp_server.shared.wiki_ir import Section
from tests_py.handlers import test_claim_event_time_synthesis as synthesis
from tests_py.handlers.test_claim_event_time_synthesis import (
    EXPECTED,
    _rows,
    _synthesise,
)

sqlite_store = synthesis.sqlite_store  # the fixture of slice 6, used by name


def _refine(store, sections: list[dict]) -> dict:
    from mcp_server.handlers.wiki_refine import handler_refine

    (row,) = _rows(store, "SELECT id FROM wiki.drafts")
    draft_id = row["id"]
    return asyncio.run(handler_refine({"draft_id": draft_id, "sections": sections}))


def _stored_sections(store) -> list[Section]:
    (draft,) = _rows(store, "SELECT sections FROM wiki.drafts")
    sections = draft["sections"]
    if isinstance(sections, str):
        sections = json.loads(sections)
    return [Section.model_validate(s) for s in sections]


def _rewritten(draft: dict) -> list[dict]:
    """The caller's refinement: new prose, the same headings and claims."""
    return [
        {
            "heading": s["heading"],
            "body": f"Rewritten: {s['heading']}.",
            "claim_ids": s.get("claim_ids", []),
        }
        for s in draft["sections"]
    ]


def test_a_rewrite_keeps_the_event_time_of_every_claim(sqlite_store):
    claims, draft = _synthesise(sqlite_store)
    assert _refine(sqlite_store, _rewritten(draft))["updated"] is True

    sections = _stored_sections(sqlite_store)
    assert all(s.body.startswith("Rewritten: ") for s in sections)
    carried = {claims[c]: t for s in sections for c, t in s.event_times.items()}
    assert carried == EXPECTED


def test_a_claim_moved_to_another_section_takes_its_time_along(sqlite_store):
    claims, draft = _synthesise(sqlite_store)
    every_claim = sorted(claims)
    (first, *rest) = _rewritten(draft)
    first["claim_ids"] = every_claim
    for section in rest:
        section["claim_ids"] = []
    assert _refine(sqlite_store, [first, *rest])["updated"] is True

    head, *others = _stored_sections(sqlite_store)
    assert {claims[c]: t for c, t in head.event_times.items()} == EXPECTED
    assert all(s.event_times == {} for s in others)


def test_a_time_the_caller_sends_is_not_written(sqlite_store):
    """A refinement rewrites prose; it does not state a date (no invented date)."""
    claims, draft = _synthesise(sqlite_store)
    invented = {"kind": "point", "start": {"value": "1999-01-01", "precision": "day"}}
    sections = _rewritten(draft)
    for section in sections:
        section["event_times"] = {str(c): invented for c in section["claim_ids"]}
        section["claim_ids"] = [*section["claim_ids"], 10**9]  # a claim it never held
    assert _refine(sqlite_store, sections)["updated"] is True

    stored = _stored_sections(sqlite_store)
    carried = {claims[c]: t for s in stored for c, t in s.event_times.items()}
    assert carried == EXPECTED
    assert all(set(s.event_times) == set(s.claim_ids) - {10**9} for s in stored)
