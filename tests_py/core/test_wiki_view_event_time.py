"""The claim_events view window on event_time compiles safely (#717, slice 7).

Pure compilation only: which keys open a window, which errors refuse one,
and that every window value travels as a bound parameter, in UTC when the
window states a zone. What the SQL keeps is proved against PostgreSQL in
``tests_py/infrastructure/test_wiki_view_event_time_pg.py``.
"""

from __future__ import annotations

import time
from datetime import datetime

from mcp_server.core.wiki_view_event_time import compile_event_time_window
from mcp_server.core.wiki_view_executor import compile_view


def _naive(*parts: int) -> datetime:
    return datetime(*parts)  # noqa: DTZ001 — an unstated zone is the case under test


def test_a_where_block_without_window_keys_is_left_alone():
    where = {"claim_type": "decision"}
    assert compile_event_time_window(where) == (where, [], [], [])


def test_both_ends_bind_their_values_and_leave_the_other_keys():
    rest, frags, params, errors = compile_event_time_window(
        {
            "claim_type": "decision",
            "event_time_from": "2026-03-01",
            "event_time_to": "2026-04-01",
        }
    )
    assert errors == []
    assert rest == {"claim_type": "decision"}
    assert params == [_naive(2026, 4, 1), _naive(2026, 3, 1)]
    assert frags[0] == "event_time->>'kind' IN ('point', 'interval')"
    assert frags[1].startswith("NOT (")
    assert all("2026" not in f for f in frags)


def test_a_zoned_window_compares_zoned_bounds_in_utc():
    _, frags, params, errors = compile_event_time_window(
        {"event_time_from": "2026-03-01T12:00:00+02:00"}
    )
    assert errors == []
    assert params == [_naive(2026, 3, 1, 10)]
    assert not frags[1].startswith("NOT")
    assert "AT TIME ZONE 'UTC'" in frags[2]


def test_one_open_end_emits_one_comparison():
    _, frags, params, _ = compile_event_time_window({"event_time_to": "2026-04-01"})
    assert len(frags) == 3 and len(params) == 1
    assert frags[2].endswith("< %s)")


def test_a_window_that_mixes_zones_is_refused():
    *_, errors = compile_event_time_window(
        {"event_time_from": "2026-03-01", "event_time_to": "2026-04-01T00:00:00+00:00"}
    )
    assert errors == [
        "event_time_from and event_time_to must both state a zone, or neither"
    ]


def test_an_empty_or_reversed_window_is_refused():
    *_, errors = compile_event_time_window(
        {"event_time_from": "2026-04-01", "event_time_to": "2026-04-01"}
    )
    assert errors == ["event_time_from must be before event_time_to"]


def test_a_value_that_is_not_iso_8601_is_refused():
    *_, errors = compile_event_time_window({"event_time_from": "March 2026"})
    assert errors == [
        "event_time_from must be an ISO 8601 date or date-time, got 'March 2026'"
    ]


def test_a_window_key_without_a_value_is_refused():
    *_, errors = compile_event_time_window({"event_time_to": None})
    assert errors == ["event_time_to needs a value"]


def test_an_empty_key_beside_a_filled_one_is_refused_not_opened():
    compiled = compile_view(
        "table: claim_events\nwhere:\n  event_time_from:\n  event_time_to: 2026-04-01"
    )
    assert compiled.errors == ["event_time_from needs a value"]


def test_an_injection_attempt_is_a_refused_value_not_sql():
    payload = "2026-03-01'; DROP TABLE wiki.pages; --"
    compiled = compile_view(
        f"table: claim_events\nwhere:\n  event_time_from: {payload}"
    )
    assert compiled.errors and "DROP" not in compiled.sql


def test_compile_view_appends_the_window_after_the_other_filters():
    compiled = compile_view(
        "table: claim_events\nwhere:\n  claim_type: decision\n"
        "  event_time_from: 2026-03-01\nlimit: 5"
    )
    assert compiled.errors == []
    assert compiled.sql.startswith(
        "SELECT * FROM wiki.claim_events WHERE claim_type = %s AND "
    )
    assert compiled.params == ["decision", _naive(2026, 3, 1), 5]


def test_the_window_keys_are_unknown_columns_on_other_tables():
    compiled = compile_view("table: pages\nwhere:\n  event_time_from: 2026-03-01")
    assert compiled.errors == ["unknown column: 'event_time_from'"]


def test_a_zoned_end_is_converted_to_utc_whatever_the_local_zone(monkeypatch):
    monkeypatch.setenv("TZ", "Pacific/Chatham")
    time.tzset()
    try:
        *_, params, _ = compile_event_time_window(
            {"event_time_to": "2026-03-01T12:00:00+02:00"}
        )
    finally:
        monkeypatch.undo()
        time.tzset()
    assert params == [_naive(2026, 3, 1, 10)]


def test_a_window_with_only_a_zoned_end_compares_zoned_bounds():
    _, frags, _, errors = compile_event_time_window(
        {"event_time_to": "2026-03-01T12:00:00+00:00"}
    )
    assert errors == []
    assert not frags[1].startswith("NOT")


def test_an_end_that_is_not_iso_8601_is_refused_by_its_own_name():
    *_, errors = compile_event_time_window({"event_time_to": "soon"})
    assert errors == ["event_time_to must be an ISO 8601 date or date-time, got 'soon'"]
