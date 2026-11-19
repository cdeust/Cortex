"""stored_event_time reads the event_time a claim_events row stores (#717)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from mcp_server.core.claim_event_time import stored_event_time
from mcp_server.shared.wiki_ir import EventTime, TimeBound

ZONED = EventTime(
    kind="interval",
    start=TimeBound(
        value=datetime(2026, 3, 12, 10, 30, tzinfo=timezone(timedelta(hours=2))),
        precision="minute",
    ),
)
DUMPED = ZONED.model_dump(mode="json", exclude_none=True)


def test_a_missing_column_is_unknown_not_a_date():
    assert stored_event_time(None) == EventTime()


def test_postgresql_jsonb_dict_round_trips_with_precision_and_offset():
    assert stored_event_time(DUMPED) == ZONED


def test_sqlite_json_text_round_trips_with_precision_and_offset():
    assert stored_event_time(json.dumps(DUMPED)) == ZONED


def test_a_corrupt_row_raises_instead_of_guessing_a_time():
    with pytest.raises(ValidationError):
        stored_event_time({"kind": "point"})
