"""synthesize_draft keeps each claim's event time in its section (#717, slice 6)."""

from __future__ import annotations

import json

from mcp_server.core.draft_synthesizer import synthesize_draft
from mcp_server.shared.wiki_ir import EventTime

DAY = {"kind": "point", "start": {"value": "2025-03-03T00:00:00", "precision": "day"}}


def _claim(cid: int, event_time) -> dict:
    claim = {"id": cid, "text": f"We decided {cid}.", "claim_type": "decision"}
    if event_time is not ...:
        claim["event_time"] = event_time
    return claim


def test_each_claim_keeps_the_time_its_row_stores_in_any_stored_form():
    claims = [_claim(1, DAY), _claim(2, json.dumps(DAY)), _claim(3, None)]
    claims.append(_claim(4, ...))  # a row read without the column
    draft, _ = synthesize_draft(claims, kind="adr")
    (decision,) = [s for s in draft.sections if s.heading == "Decision"]
    assert decision.claim_ids == [1, 2, 3, 4]
    assert decision.event_times == {
        1: EventTime.model_validate(DAY),
        2: EventTime.model_validate(DAY),
        3: EventTime(),
        4: EventTime(),
    }


def test_an_empty_section_names_no_time_and_a_claim_without_id_none():
    draft, _ = synthesize_draft(
        [{"text": "We decided.", "claim_type": "decision"}], kind="adr"
    )
    assert all(s.event_times == {} for s in draft.sections)


def test_the_page_carries_no_event_date_of_its_own():
    draft, _ = synthesize_draft([_claim(1, DAY)], kind="adr")
    assert not {"event_time", "date", "start", "end"} & set(draft.frontmatter)


def test_required_sections_stay_in_order_and_only_filled_optional_ones_appear():
    from mcp_server.shared.wiki_schema_loader import KindDefinition

    kind = KindDefinition(
        name="adr",
        display_name="ADR",
        dir_name="adr",
        required_sections=["Decision", "Context"],
        optional_sections=["Alternatives Considered", "References"],
    )
    claims = [
        _claim(1, DAY),
        {"id": 2, "text": "See RFC 9562.", "claim_type": "reference"},
    ]
    draft, _ = synthesize_draft(claims, kind="adr", kind_definition=kind)
    by_heading = {s.heading: s for s in draft.sections}
    assert list(by_heading) == ["Decision", "Context", "References"]
    assert by_heading["Decision"].event_times == {1: EventTime.model_validate(DAY)}
    assert by_heading["Context"].body == "_(to be filled)_"
    assert by_heading["References"].claim_ids == [2]
    assert by_heading["References"].event_times == {2: EventTime()}
    assert by_heading["References"].body == "See RFC 9562."
