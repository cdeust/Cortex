"""A claim's event time is the date its sentence states, at that precision (#717).

source: issue #717 slice 3; mcp_server/core/claim_event_time.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.core.claim_event_time import stated_event_time
from mcp_server.core.claim_extractor import extract_claims


def _naive(*parts: int) -> datetime:
    """A time whose source names no zone: the naive value is the point."""
    return datetime(*parts)  # noqa: DTZ001 — an unstated zone is the case under test


def _point(sentence: str) -> tuple[datetime, str]:
    event = stated_event_time(sentence)
    assert event.kind == "point", event
    assert event.end is None
    assert event.start is not None
    return event.start.value, event.start.precision


@pytest.mark.parametrize(
    ("sentence", "value", "precision"),
    [
        ("We decided to drop Redis in March 2026.", _naive(2026, 3, 1), "month"),
        ("We decided on 12 March 2026 to drop Redis.", _naive(2026, 3, 12), "day"),
        ("On March 12, 2026 we switched to SQLite.", _naive(2026, 3, 12), "day"),
        ("On March 9 2026 we switched to SQLite.", _naive(2026, 3, 9), "day"),
        ("In May 2025 we adopted pgvector.", _naive(2025, 5, 1), "month"),
        ("The 2026-03 release adopted pgvector.", _naive(2026, 3, 1), "month"),
        ("The run of 2026-03-12 measured 0.9.", _naive(2026, 3, 12), "day"),
        ("2026-03-12: we decided to drop Redis.", _naive(2026, 3, 12), "day"),
        ("Measured on 2026-03: latency was 10 ms.", _naive(2026, 3, 1), "month"),
        (
            "Deployed 2026-03-12T10:30 to staging.",
            _naive(2026, 3, 12, 10, 30),
            "minute",
        ),
        (
            "Deployed 2026-03-12T10:30:15 to staging.",
            _naive(2026, 3, 12, 10, 30, 15),
            "second",
        ),
    ],
)
def test_a_stated_date_keeps_exactly_its_precision(sentence, value, precision):
    assert _point(sentence) == (value, precision)


@pytest.mark.parametrize(
    ("sentence", "offset"),
    [
        ("Failed at 2026-03-12T10:30Z on CI.", timedelta(0)),
        ("Failed at 2026-03-12T10:30+02:00 on CI.", timedelta(hours=2)),
        ("Failed at 2026-03-12T10:30-05:00 on CI.", timedelta(hours=-5)),
        ("Failed at 2026-03-12T10:30+0530 on CI.", timedelta(hours=5, minutes=30)),
        ("Failed at 2026-03-12T10:30+05:59 on CI.", timedelta(hours=5, minutes=59)),
    ],
)
def test_a_stated_offset_is_kept(sentence, offset):
    value, precision = _point(sentence)
    assert precision == "minute"
    assert value.utcoffset() == offset
    assert value.replace(tzinfo=None) == _naive(2026, 3, 12, 10, 30)


def test_a_time_without_a_zone_stays_naive():
    value, _ = _point("Deployed 2026-03-12T10:30 to staging.")
    assert value.tzinfo is None


@pytest.mark.parametrize(
    "sentence",
    [
        "We decided to drop Redis.",
        "",
        "Smith 1992 found that recall decays.",
        "It may 2026 be fine to use it.",
        "Yesterday we decided to drop Redis.",
        "The 2026-02-30 run failed.",
        "The 2026-13 release failed.",
        "Failed at 2026-03-12T10:30+25:00 on CI.",
        "Logged at 2026-03-12T10:30:15.123Z by the worker.",
        "Logged at 2026-03-12T10:30:15.1 by the worker.",
        "Logged at 2026-03-12T10:30:15,5 by the worker.",
        "Failed at 2026-03-12T10:30+05:60 on CI.",
        "We decided to drop Redis. On March 12, 2026 we measured throughput.",
        "The file notes-2026-03-12.md uses the cache.",
        "Tested 2026-03-12x builds only.",
        "The range 1999-2001 was measured.",
        "From 2026-01 to 2026-03 we used Redis.",
        "Between March 2026 and 4 April 2026 we used Redis.",
        "On 12 March 2026, not May 3, 2026, we used Redis.",
        "Planned for 12 March 2026, shipped on 2026-04-02.",
        "Failed at 2026-03-12T10:00Z and 2026-03-12T12:00+02:00.",
    ],
)
def test_no_single_stated_date_leaves_the_event_time_unknown(sentence):
    event = stated_event_time(sentence)
    assert event.kind == "unknown"
    assert event.start is None and event.end is None


def test_the_same_date_written_twice_is_one_point():
    assert _point("On 12 March 2026 (2026-03-12) we switched.") == (
        _naive(2026, 3, 12),
        "day",
    )


def test_a_historical_event_keeps_its_date_apart_from_extraction():
    claims, _ = extract_claims(
        "We decided to drop Redis in March 2019.\n\n"
        "We decided to keep SQLite as the default store."
    )
    dated, undated = claims
    assert dated.extracted_at is None
    assert dated.event_time.kind == "point"
    assert dated.event_time.start is not None
    assert dated.event_time.start.value == _naive(2019, 3, 1)
    assert dated.event_time.start.precision == "month"
    assert undated.event_time.kind == "unknown"


def test_each_claim_reads_only_its_own_sentence():
    para = (
        "We decided to drop Redis on 12 March 2026 after the outage that "
        "lasted the whole afternoon. We will use SQLite as the default "
        "store from now on, for every new installation."
    )
    claims, _ = extract_claims(para)
    assert [c.event_time.kind for c in claims] == ["point", "unknown"]


def test_utc_is_the_utc_singleton():
    value, _ = _point("Failed at 2026-03-12T10:30Z on CI.")
    assert value.tzinfo is timezone.utc


def test_a_date_in_a_neighbouring_sentence_does_not_date_the_claim():
    claims, _ = extract_claims(
        "We decided to drop Redis. On March 12, 2026 we measured throughput."
    )
    assert [c.event_time.kind for c in claims] == ["unknown"]
