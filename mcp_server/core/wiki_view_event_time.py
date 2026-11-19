"""A claim_events view filter on the event time a claim states (#717, slice 7).

source: issue #717 (decision comment of 2026-11-19, "Recherche"): a bound
covers the span its precision names ("March 2026" is [2026-03-01,
2026-04-01)); a filter keeps a claim whose span overlaps the requested
window; a bound without a zone is not comparable with a window that has one,
nor the reverse, and is not kept (nothing is converted). Strict inclusion is
set aside: it would drop a month-precise date from a day-wide window inside it.

The window is half-open, ``[event_time_from, event_time_to)``, each end an ISO
8601 date or date-time read by ``datetime.fromisoformat``; either end may be
left out (open window). A claim's span is ``[lo, hi)``: ``lo`` is its start
value (unbounded when the interval has no start), ``hi`` its end value (the
start for a point) plus one unit of that bound's precision (unbounded when the
interval has no end). ``unknown`` event times are never kept. Zoned values
are compared in UTC, the unit being added in the bound's stated offset first,
so the session ``TimeZone`` changes nothing.

Only SQL text built from fixed strings leaves this module; the window values
travel as bound parameters (ADR-0318).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

WINDOW_KEYS = ("event_time_from", "event_time_to")

# source: pydantic's JSON form of an aware datetime ("Z" or "+HH:MM"), the form
# wiki_extract._claim_to_dict stores (model_dump(mode="json")); #717
_ZONED = r"'(Z|[+-][0-9]{2}:[0-9]{2})$'"
_ANY_VALUE = "COALESCE(event_time->'start'->>'value', event_time->'end'->>'value')"


def _wall(bound: str) -> str:
    """The bound's stated wall clock; PostgreSQL ignores an offset in this cast."""
    return f"(event_time->'{bound}'->>'value')::timestamp"


def _utc(bound: str) -> str:
    return f"((event_time->'{bound}'->>'value')::timestamptz AT TIME ZONE 'UTC')"


def _value(bound: str, zoned: bool) -> str:
    return _utc(bound) if zoned else _wall(bound)


def _upper(bound: str, zoned: bool) -> str:
    """The exclusive end of the span the bound covers at its own precision.

    A zoned bound adds its unit in its stated offset, then moves to UTC: a month
    added in UTC would take the length of the UTC month, which differs when the
    offset crosses a month boundary ("2027-03-01T00:00+02:00" is February in UTC).
    """
    step = f"('1 ' || (event_time->'{bound}'->>'precision'))::interval"
    end = f"({_wall(bound)} + {step})"
    return f"({end} - ({_wall(bound)} - {_utc(bound)}))" if zoned else end


def _parse_end(key: str, where: dict[str, Any]) -> tuple[datetime | None, str | None]:
    """The window end ``key`` names; a key present without a value is an error."""
    if key not in where:
        return None, None
    raw = where[key]
    if raw is None:
        return None, f"{key} needs a value"
    try:
        return datetime.fromisoformat(str(raw)), None
    except ValueError:
        return None, f"{key} must be an ISO 8601 date or date-time, got {raw!r}"


def _window(
    where: dict[str, Any],
) -> tuple[datetime | None, datetime | None, list[str]]:
    start, start_err = _parse_end(WINDOW_KEYS[0], where)
    end, end_err = _parse_end(WINDOW_KEYS[1], where)
    errors = [e for e in (start_err, end_err) if e]
    if not errors and start and end:
        if (start.utcoffset() is None) != (end.utcoffset() is None):
            errors.append(
                "event_time_from and event_time_to must both state a zone, or neither"
            )
        elif start >= end:
            errors.append("event_time_from must be before event_time_to")
    return start, end, errors


def _as_utc_naive(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def compile_event_time_window(
    where: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[Any], list[str]]:
    """Split the event-time window out of a claim_events ``where`` block.

    precondition: ``where`` is the view's flat where dict.
    postcondition: returns (the where dict without the window keys, SQL
    fragments, their bound parameters in order, errors); no fragment when the
    where block names no window key.
    """
    rest = {k: v for k, v in where.items() if k not in WINDOW_KEYS}
    if not any(k in where for k in WINDOW_KEYS):
        return rest, [], [], []
    start, end, errors = _window(where)
    if errors:
        return rest, [], [], errors
    stated = start if start is not None else end
    zoned = stated is not None and stated.utcoffset() is not None
    frags = [
        "event_time->>'kind' IN ('point', 'interval')",
        f"{'' if zoned else 'NOT '}({_ANY_VALUE} ~ {_ZONED})",
    ]
    params: list[Any] = []
    if end is not None:
        frags.append(
            f"(event_time->'start'->>'value' IS NULL OR {_value('start', zoned)} < %s)"
        )
        params.append(_as_utc_naive(end))
    if start is not None:
        frags.append(
            f"(CASE WHEN event_time->>'kind' = 'point' THEN {_upper('start', zoned)}"
            " WHEN event_time->'end'->>'value' IS NULL THEN 'infinity'::timestamp"
            f" ELSE {_upper('end', zoned)} END) > %s"
        )
        params.append(_as_utc_naive(start))
    return rest, frags, params, []


__all__ = ["WINDOW_KEYS", "compile_event_time_window"]
