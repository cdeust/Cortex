"""Explicit timezone policy for free-form date normalization.

source: ADR-0671"""

from __future__ import annotations

# source: ADR-0671


_RFC5322_ZONE_OFFSET_HOURS: dict[str, int] = {
    "UT": 0,
    "GMT": 0,
    "EST": -5,
    "EDT": -4,
    "CST": -6,
    "CDT": -5,
    "MST": -7,
    "MDT": -6,
    "PST": -8,
    "PDT": -7,
}

# source: ADR-0671
_SECONDS_PER_HOUR = 3600

#: The abbreviations this policy resolves, for operator-facing messages.
RFC5322_ZONE_NAMES: tuple[str, ...] = tuple(sorted(_RFC5322_ZONE_OFFSET_HOURS))


class RFC5322ZoneResolver:
    """Single-use `tzinfos` resolver for `dateutil.parser.parse`.

    dateutil calls the resolver with the timezone abbreviation it read and the
    numeric offset it already resolved (either may be None) and expects an
    offset in seconds, a `tzinfo`, or None. This resolver:

    source: ADR-0671

    Passing a resolver also disables dateutil's own fallbacks: it no longer
    resolves an abbreviation that happens to match the *host's* local zone
    name, and it no longer emits `UnknownTimezoneWarning`. Parsing is
    therefore identical on every machine.

    One instance per parse — `unresolved` is per-call state, never shared.
    """

    __slots__ = ("unresolved",)

    def __init__(self) -> None:
        self.unresolved: str | None = None

    def __call__(self, tzname: str | None, tzoffset: int | None) -> int | None:
        """Resolve one zone token; record it when the table has no row."""
        if tzoffset is not None:
            return tzoffset
        if tzname is None:
            return None
        offset_hours = _RFC5322_ZONE_OFFSET_HOURS.get(tzname.upper())
        if offset_hours is None:
            self.unresolved = tzname
            return None
        return offset_hours * _SECONDS_PER_HOUR
