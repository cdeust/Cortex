"""Normalization of a free-form date string to ISO 8601 for storage.

source: ADR-0670"""

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

# source: ADR-0670


_ISO_DATETIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)

# source: ADR-0670


_TIME_OF_DAY_RE = re.compile(r"\d{1,2}:\d{2}")

# source: ADR-0670


_STATED_ZONE_RE = re.compile(r"(?:[+-]\d{2}:?\d{2}|\b[A-Z]{2,5})\s*$")


def normalize_date_to_iso(raw: str) -> str | None:
    """Normalize a free-form date string to ISO 8601 for storage.

    source: ADR-0670

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
        from dateutil import parser as dateutil_parser  # noqa: PLC0415 — source: ADR-0670
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
