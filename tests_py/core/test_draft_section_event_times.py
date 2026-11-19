"""Unit cases of ``carry_event_times`` (#717, slice 8)."""

from __future__ import annotations

from mcp_server.core.draft_section_event_times import (
    carry_event_times,
    draft_event_times,
)

POINT = {"kind": "point", "start": {"value": "2025-03-03T00:00:00", "precision": "day"}}
UNKNOWN = {"kind": "unknown"}
STORED = [
    {"heading": "Decision", "body": "b", "claim_ids": [5], "event_times": {"5": POINT}},
    {
        "heading": "Context",
        "body": "c",
        "claim_ids": [6],
        "event_times": {"6": UNKNOWN},
    },
    {"heading": "Status", "body": "_(to be filled)_", "claim_ids": []},
]


def test_the_draft_times_are_keyed_by_integer_claim_id():
    assert draft_event_times(STORED) == {5: POINT, 6: UNKNOWN}


def test_each_section_times_exactly_the_stored_claims_it_cites():
    refined = [
        {"heading": "Decision", "body": "new", "claim_ids": [6, 5]},
        {"heading": "Context", "body": "new"},
    ]
    assert carry_event_times(refined, STORED) == [
        {
            "heading": "Decision",
            "body": "new",
            "claim_ids": [6, 5],
            "event_times": {"6": UNKNOWN, "5": POINT},
        },
        {"heading": "Context", "body": "new", "event_times": {}},
    ]


def test_ids_that_name_no_timed_claim_get_no_time():
    refined = [{"heading": "D", "body": "x", "claim_ids": [7, "5", True, {}, None]}]
    (section,) = carry_event_times(refined, STORED)
    assert section["event_times"] == {}
    assert section["claim_ids"] == [7, "5", True, {}, None]  # the caller's, untouched


def test_the_caller_time_is_replaced_by_the_stored_one():
    refined = [
        {"heading": "D", "body": "x", "claim_ids": [5], "event_times": {"5": UNKNOWN}}
    ]
    (section,) = carry_event_times(refined, STORED)
    assert section["event_times"] == {"5": POINT}


def test_a_draft_written_before_event_times_carries_none():
    legacy = [{"heading": "D", "body": "b", "claim_ids": [5]}]
    refined = [{"heading": "D", "body": "x", "claim_ids": [5]}]
    assert carry_event_times(refined, legacy)[0]["event_times"] == {}


def test_the_refined_input_is_not_mutated():
    refined = [{"heading": "D", "body": "x", "claim_ids": [5], "event_times": {}}]
    carry_event_times(refined, STORED)
    assert refined == [
        {"heading": "D", "body": "x", "claim_ids": [5], "event_times": {}}
    ]
