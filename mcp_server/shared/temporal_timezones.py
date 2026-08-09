"""Explicit timezone policy for free-form date normalization.

`dateutil.parser.parse` drops a timezone abbreviation it cannot resolve and
returns a *naive* datetime. Every downstream reader then reads that naive
value as UTC (`temporal.compute_recency_boost`, PostgreSQL's `timestamptz`
cast), so `13:56 EST` is persisted as `13:56+00:00` — five hours off, with
nothing emitted (issue #252).

This module supplies the `tzinfos` resolver that closes the hole: a stated
abbreviation either resolves through a cited table, or the caller is told the
name it could not resolve so it can refuse the value. The zone is never
dropped.

The alternative fix — wrapping the parse in `warnings.catch_warnings()` and
promoting dateutil's `UnknownTimezoneWarning` to an error — mutates
process-global filter state and is documented as not thread-safe; on a store
write path that is worse than the defect it closes.

Pure business logic -- no I/O.
"""

from __future__ import annotations

# Offsets, in hours from UTC, of the alphabetic zone abbreviations that
# RFC 5322 §4.3 ("Obsolete Date and Time", obs-zone) binds to a numeric
# offset. This table is the normative answer to "which EST?": the RFC fixes
# EST at -0500 (US Eastern), so each row is a citation rather than a guess.
# Abbreviations outside it (single-letter military zones, "IST", "CET", ...)
# are deliberately absent — RFC 5322 states the military zones were defined
# in a non-standard way and are "unpredictable in their meaning", and that any
# other unknown alphabetic zone SHOULD be read as "-0000" (unknown local
# offset). Persisting that default as an instant IS the defect this module
# exists to prevent, so an absent row is refused, never defaulted.
# source: RFC 5322 §4.3 (Resnick, 2008), the obs-zone offset table;
# cross-checked row for row against CPython's implementation of the same
# table in Lib/email/_parseaddr.py (`_timezones`).
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

# source: SI derived unit — 1 h = 60 min x 60 s.
_SECONDS_PER_HOUR = 3600

#: The abbreviations this policy resolves, for operator-facing messages.
RFC5322_ZONE_NAMES: tuple[str, ...] = tuple(sorted(_RFC5322_ZONE_OFFSET_HOURS))


class RFC5322ZoneResolver:
    """Single-use `tzinfos` resolver for `dateutil.parser.parse`.

    dateutil calls the resolver with the timezone abbreviation it read and the
    numeric offset it already resolved (either may be None) and expects an
    offset in seconds, a `tzinfo`, or None. This resolver:

    * returns an already-resolved numeric offset unchanged — that covers
      `+02:00`, `UTC`, `GMT` and `Z`, which dateutil hands over as offset 0;
    * resolves an RFC 5322 §4.3 abbreviation to its offset;
    * records any other abbreviation in `unresolved` and returns None.

    Returning None makes dateutil build a naive datetime, so a caller MUST
    check `unresolved` after the parse and refuse the value. That check is
    what turns a dropped zone into a refusal instead of a silent re-anchor.

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
