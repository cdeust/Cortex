"""ClaimEvent keeps the event's own time apart from its extraction time (#717).

Acceptance evidence of #717 this slice covers: a historical event extracted
today keeps its occurrence separately from ``extracted_at``; unknown, point
and interval dates round-trip with their precision and timezone; nothing
invents a date or a precision the source did not state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from mcp_server.shared.wiki_ir import ClaimEvent, EventTime, TimeBound

_PARIS_SUMMER = timezone(timedelta(hours=2))


def _unzoned(*parts: int) -> datetime:
    """A time whose source names no zone: the naive value is the point."""
    return datetime(*parts)  # noqa: DTZ001 — an unstated zone is the case under test


def _round_trip(claim: ClaimEvent) -> ClaimEvent:
    return ClaimEvent.model_validate_json(claim.model_dump_json())


def test_historical_event_keeps_its_occurrence_apart_from_extraction():
    extracted = datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc)
    occurred = EventTime(
        kind="point", start=TimeBound(value=_unzoned(1969, 7, 20), precision="day")
    )
    claim = ClaimEvent(
        text="Apollo 11 landed.", extracted_at=extracted, event_time=occurred
    )

    back = _round_trip(claim)

    assert back.extracted_at == extracted
    assert back.event_time == occurred
    assert back.event_time.start.value.year == 1969


def test_claim_without_stated_date_is_unknown_not_its_extraction_time():
    claim = ClaimEvent(text="The cache is pruned.", extracted_at=_unzoned(2026, 11, 5))

    assert claim.event_time.kind == "unknown"
    assert claim.event_time.start is None and claim.event_time.end is None
    assert _round_trip(claim).event_time == EventTime()


@pytest.mark.parametrize(
    "event_time",
    [
        EventTime(),
        EventTime(
            kind="point", start=TimeBound(value=_unzoned(2026, 3, 1), precision="month")
        ),
        EventTime(
            kind="point",
            start=TimeBound(
                value=datetime(2026, 3, 4, 14, 5, tzinfo=_PARIS_SUMMER),
                precision="minute",
            ),
        ),
        EventTime(
            kind="interval",
            start=TimeBound(value=_unzoned(2024, 1, 1), precision="year"),
            end=TimeBound(value=_unzoned(2025, 6, 1), precision="month"),
        ),
        EventTime(
            kind="interval",
            end=TimeBound(value=_unzoned(2026, 10, 10), precision="day"),
        ),
    ],
    ids=[
        "unknown",
        "point-month",
        "point-minute-offset",
        "interval-closed",
        "interval-open-start",
    ],
)
def test_event_time_round_trips_with_precision_and_zone(event_time):
    back = _round_trip(ClaimEvent(text="claim", event_time=event_time))

    assert back.event_time == event_time
    for sent, got in (
        (event_time.start, back.event_time.start),
        (event_time.end, back.event_time.end),
    ):
        if sent is not None:
            assert got.precision == sent.precision
            assert got.value.utcoffset() == sent.value.utcoffset()


@pytest.mark.parametrize(
    ("value", "precision"),
    [
        (_unzoned(2026, 3, 4), "month"),
        (_unzoned(2026, 2, 1), "year"),
        (_unzoned(2026, 3, 4, 10), "day"),
        (_unzoned(2026, 3, 4, 10, 5, 7), "minute"),
        (_unzoned(2026, 3, 4, 10, 5, 7, 1), "second"),
    ],
)
def test_bound_rejects_components_finer_than_its_precision(value, precision):
    with pytest.raises(ValidationError, match="finer than precision"):
        TimeBound(value=value, precision=precision)


_MARCH = TimeBound(value=_unzoned(2026, 3, 1), precision="month")
_APRIL = TimeBound(value=_unzoned(2026, 4, 1), precision="month")
_APRIL_UTC = TimeBound(
    value=datetime(2026, 4, 1, tzinfo=timezone.utc), precision="month"
)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"kind": "unknown", "start": _MARCH}, "carries no bound"),
        ({"kind": "point"}, "start only"),
        ({"kind": "point", "start": _MARCH, "end": _APRIL}, "start only"),
        ({"kind": "interval"}, "at least one bound"),
        ({"kind": "interval", "start": _APRIL, "end": _MARCH}, "after its end"),
        ({"kind": "interval", "start": _MARCH, "end": _APRIL_UTC}, "both state a zone"),
    ],
)
def test_event_time_rejects_bounds_that_contradict_its_kind(fields, message):
    with pytest.raises(ValidationError, match=message):
        EventTime(**fields)
