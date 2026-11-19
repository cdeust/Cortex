"""wiki_view keeps the claims whose stated event time overlaps a window (#717).

Slice 7 of #717, the rule written in the issue's decision of 2026-11-19: a
bound covers the span its precision names ("March 2026" is the whole month),
a claim is kept when that span overlaps the half-open window
``[event_time_from, event_time_to)``, an ``unknown`` event time is never kept,
and a naive bound is not compared with a zoned window, nor the reverse.
Runs the SQL ``compile_view`` builds on the PostgreSQL store, where
``wiki_view`` executes it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mcp_server.core.wiki_view_executor import compile_view
from mcp_server.handlers.wiki_extract import _claim_to_dict
from mcp_server.infrastructure.pg_store_wiki_claims import insert_claim_events
from mcp_server.infrastructure.row_factory import DICT_ROW
from mcp_server.shared.wiki_ir import ClaimEvent, EventTime, TimeBound
from tests_py.conftest import _USE_PG

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL test database not reachable"
)

_PLUS_TWO = timezone(timedelta(hours=2))


def _naive(*parts: int) -> datetime:
    return datetime(*parts)  # noqa: DTZ001 — an unstated zone is the case under test


def _point(value: datetime, precision: str) -> EventTime:
    return EventTime(kind="point", start=TimeBound(value=value, precision=precision))


CLAIMS = {
    "march": _point(_naive(2026, 3, 1), "month"),
    "march-12": _point(_naive(2026, 3, 12), "day"),
    "april-1": _point(_naive(2026, 4, 1), "day"),
    "until-2025": EventTime(
        kind="interval", end=TimeBound(value=_naive(2025, 1, 1), precision="year")
    ),
    "since-may": EventTime(
        kind="interval", start=TimeBound(value=_naive(2026, 5, 1), precision="month")
    ),
    "zoned-noon": _point(datetime(2026, 3, 12, 12, 0, tzinfo=_PLUS_TWO), "minute"),
    "unknown": EventTime(),
}


@pytest.fixture
def store():
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    s = PgMemoryStore()
    mid = s.insert_memory({"content": "event time window #717", "domain": "t717"})
    claims = [
        ClaimEvent(text=name, memory_id=mid, event_time=et)
        for name, et in CLAIMS.items()
    ]
    insert_claim_events(s._conn, [_claim_to_dict(c) for c in claims])
    yield s, mid
    s._conn.rollback()
    s.close()


def _kept(store, window: str) -> set[str]:
    s, mid = store
    compiled = compile_view(
        f"table: claim_events\nwhere:\n  memory_id: {mid}\n{window}limit: 500"
    )
    assert compiled.errors == []
    with s._conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(compiled.sql, compiled.params)
        return {r["text"] for r in cur.fetchall()}


_NAIVE = {"march", "march-12", "april-1", "until-2025", "since-may"}


@pytest.mark.parametrize(
    ("window", "kept"),
    [
        # a month-precise date overlaps a day inside it; the day itself too
        ({"from": "2026-03-12", "to": "2026-03-13"}, {"march", "march-12"}),
        # half-open: a date on the window's end is outside it
        ({"from": "2026-03-01", "to": "2026-04-01"}, {"march", "march-12"}),
        # "until 2025" covers the whole of 2025; "since May" has no end
        ({"from": "2025-06-01"}, _NAIVE),
        ({"to": "2025-06-01"}, {"until-2025"}),
        ({"from": "2026-06-01", "to": "2026-07-01"}, {"since-may"}),
        # 12:00+02:00 is 10:00 UTC; its minute is [10:00, 10:01)
        (
            {"from": "2026-03-12T09:30:00+00:00", "to": "2026-03-12T10:30:00+00:00"},
            {"zoned-noon"},
        ),
        (
            {"from": "2026-03-12T10:01:00+00:00", "to": "2026-03-12T11:00:00+00:00"},
            set(),
        ),
    ],
)
def test_the_window_keeps_exactly_the_claims_whose_span_overlaps_it(
    store, window, kept
):
    lines = "".join(f"  event_time_{end}: {value}\n" for end, value in window.items())
    assert _kept(store, lines) == kept


def test_a_naive_window_never_keeps_a_zoned_claim_nor_an_unknown_one(store):
    everything = "  event_time_from: 0001-01-02\n  event_time_to: 9999-12-30\n"
    assert _kept(store, everything) == _NAIVE
