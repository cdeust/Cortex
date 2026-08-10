"""Normalization of a free-form date string to ISO 8601 for storage.

Separate from `temporal.py`, which scores dates for retrieval: the two have
different reasons to change. Scoring answers "how close is this date to the
query?" and may drop precision freely; storage normalization answers "which
instant does this string denote?" and may not — a dropped timezone is read as
UTC by every downstream consumer (PostgreSQL's `timestamptz` cast,
`temporal.compute_recency_boost`), so it silently persists the wrong instant
(issue #252).

Pure business logic -- no I/O.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from mcp_server.shared.temporal import parse_date
from mcp_server.shared.temporal_timezones import (
    RFC5322_ZONE_NAMES,
    RFC5322ZoneResolver,
)

logger = logging.getLogger(__name__)

# A complete ISO 8601 date-time of day, which is stored verbatim.
# source: ISO 8601-1:2019 §5.4.2 (<date>T<time> combination) with the §4.3.13
# UTC designator / §4.3.14 offset optional. Anchored at both ends: a substring
# test ("T" in raw) matched any string merely CONTAINING a capital T — every
# US zone abbreviation does ("EST", "PST", "CST", "MST") — and returned it
# unparsed (issue #252).
_ISO_DATETIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)

# A time of day anywhere in the string. `parse_date` reads the date and
# discards whatever follows it, so on a string that states a time (and
# possibly a zone) that fast path would silently move the instant to midnight.
_TIME_OF_DAY_RE = re.compile(r"\d{1,2}:\d{2}")

# A timezone the string STATES: a trailing numeric UTC offset, or the trailing
# 2-5 letter uppercase abbreviation shape of RFC 5322 §4.3's obs-zone. Matched
# structurally, not resolved: this only has to answer "did the producer state a
# zone?", so that a value whose zone could not be APPLIED is refused instead of
# salvaged. Salvaging it would return a naive date, and a naive date is read as
# UTC by every consumer — the defect of issue #252, reintroduced through the
# degraded path.
_STATED_ZONE_RE = re.compile(r"(?:[+-]\d{2}:?\d{2}|\b[A-Z]{2,5})\s*$")


def normalize_date_to_iso(raw: str) -> str | None:
    """Normalize a free-form date string to ISO 8601 for storage.

    Handles formats like '1:56 pm on 8 May, 2023' (LoCoMo),
    '8 May 2023', 'May 8, 2023', ISO strings, and other common formats.
    Falls back to dateutil for complex formats with time components.

    A stated timezone is honoured or the value is refused: an abbreviation
    outside the RFC 5322 §4.3 table (see `temporal_timezones`) is never
    dropped, because a dropped zone reads as UTC everywhere downstream.

    Returns ISO string or None if unparseable.
    """
    raw = raw.strip()
    if not raw:
        return None
    if _ISO_DATETIME_RE.match(raw):
        return raw
    # Fast built-in parsers, only for strings that state no time of day.
    if not _TIME_OF_DAY_RE.search(raw):
        dt = parse_date(raw)
        if dt:
            return dt.isoformat()
    return _normalize_under_zone_policy(raw)


def _parse_with_resolver(raw: str, resolver: RFC5322ZoneResolver) -> datetime | None:
    """Run dateutil under `resolver`, or None when it cannot produce a value."""
    try:
        from dateutil import parser as dateutil_parser  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        logger.warning(
            "Cannot normalize date %r: python-dateutil is not installed, so "
            "only date-only formats are parseable. Install python-dateutil to "
            "store the time of day and timezone of free-form dates.",
            raw,
        )
        return None
    try:
        return dateutil_parser.parse(raw, tzinfos=resolver)
    except (ValueError, OverflowError):
        return None


def _normalize_under_zone_policy(raw: str) -> str | None:
    """Parse under an explicit timezone policy; refuse an unresolvable zone."""
    resolver = RFC5322ZoneResolver()
    parsed = _parse_with_resolver(raw, resolver)
    if resolver.unresolved is not None:
        logger.warning(
            "Refusing date %r: timezone abbreviation %r is not resolvable "
            "(RFC 5322 §4.3 defines only %s), and re-anchoring it to UTC would "
            "store the wrong instant. Emit a numeric UTC offset (e.g. -05:00) "
            "instead; this value was NOT normalized.",
            raw,
            resolver.unresolved,
            ", ".join(RFC5322_ZONE_NAMES),
        )
        return None
    if parsed is not None:
        return parsed.isoformat()
    if _STATED_ZONE_RE.search(raw):
        logger.warning(
            "Refusing date %r: it states a timezone, and the parse that would "
            "apply it did not produce a value. Salvaging the date alone would "
            "store a naive timestamp, which every consumer reads as UTC; this "
            "value was NOT normalized.",
            raw,
        )
        return None
    salvaged = parse_date(raw)
    if salvaged is None:
        return None
    logger.warning(
        "Date %r states a time of day that is not parseable; storing the date "
        "alone (%s), so its time is lost.",
        raw,
        salvaged.date().isoformat(),
    )
    return salvaged.isoformat()
