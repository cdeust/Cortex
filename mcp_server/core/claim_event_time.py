"""A claim's event time, read from the date its own sentence states (#717).

source: issue #717 (slice 3: "extract stated dates with their precision, never
falling back on extracted_at"); ISO 8601-1:2019 §5.2 (calendar dates, reduced
precision YYYY-MM), §5.3 (time of day), §5.3.4 (UTC offset).

Only a date written in the sentence becomes an event time, at exactly the
precision written: "March 2026" is a month, "2026-03-12T10:30+02:00" a minute
with its offset. ``shared/temporal_normalize.normalize_date_to_iso`` is not
used: it fills the components a source leaves out ("March 2026" ->
2026-03-06 when run on 2026-11-06, "2019" -> 2019-11-06, measured 2026-11-06,
CPython 3.11, python-dateutil from uv.lock), which is the invented precision
``TimeBound`` refuses.

Not read, so they stay ``unknown``: a bare year (indistinguishable here from a
citation such as "Bjork 1992" or a count), relative dates ("yesterday", which
need an anchor the sentence does not give), fractional seconds, with a
period or ISO's comma (finer than ``TemporalPrecision``), an offset whose
minutes exceed 59, a sentence stating two or more different dates
(which one is the event's is not decidable from the text; choosing one would
invent it), and a unit holding several sentences or lines, as the extractor
keeps a short paragraph, a heading or a list item whole: a date there may belong to
the sentence that is not the claim. A date inside a URL, a path or a file name
("./2026-03-12/report.md") is a reference, not a stated date. Known limit: a
short year range such as "2010-11" is read as the month it also spells in ISO
8601.

Intervals (slice 4): "from D1 to|until|till|through D2" and "between D1 and D2"
give both bounds; "since D" a start with an unknown end; "until|till D" an end
with an unknown start. Each bound keeps its own written precision and zone. Only
full dates bound an interval: in "from 10 to 12 March 2026" or "10-12 March
2026" the first end names no month and no year, and copying them from the
second end would state what the sentence does not, so these stay unknown, as
does any other interval wording, an end before the start, and a pair where only
one end states a zone.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from mcp_server.shared.wiki_ir import EventTime, TemporalPrecision, TimeBound

# source: ADR-0123 -- the extractor's sentence boundary, defined once here.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[\(\#\*\d])")

# source: ISO 8601-1:2019 §5.2.2/§5.2.3/§5.3.1.2/§5.3.4 (extended format)
_ISO_RE = re.compile(
    r"(?<![\w-])(\d{4})-(\d{2})(?:-(\d{2})"
    r"(?:T(\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:?\d{2})?)?)?"
    r"(?![\w+-]|[:.,]\d)"
)
# source: Gregorian calendar month names; capitalised only, so the modal
# "may" is never read as a month.
_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()
_MONTH_GROUP = "|".join(_MONTHS)
# One alternation, longest form first, so each written date is one match.
_NAMED_RE = re.compile(
    rf"\b(?:(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_GROUP})"
    rf"|(?P<month_first>{_MONTH_GROUP})\s+(?P<day_second>\d{{1,2}}),?"
    rf"|(?P<month_only>{_MONTH_GROUP}))\s+(?P<year>\d{{4}})\b"
)
# source: #717 -- interval wording next to a date ("from 10 to 12 March",
# "since 2026-01", "10-12 March"): a point is never read from it.
_RANGE_RE = re.compile(
    rf"(?i:\b(?:from|between|since|until|till|through))\s+(?:\d|(?:{_MONTH_GROUP})\b)"
    rf"|\b\d{{1,2}}\s*(?:-|\u2013|\u2014|to|and)\s*\d{{1,2}}\s+(?:{_MONTH_GROUP})\b"
)
# source: #717 slice 4 -- English interval frames: (word before the first date,
# words between the two dates) for a closed interval; the word before a single
# date for an interval open at its end ("since") or at its start ("until").
_CLOSED_FRAMES = frozenset(
    [("from", w) for w in ("to", "until", "till", "through")] + [("between", "and")]
)
_OPEN_END_WORDS = frozenset({"since"})
_OPEN_START_WORDS = frozenset({"until", "till"})
# source: a closed interval has two ends, a start and an end (EventTime)
_CLOSED_ENDS = 2
# Punctuation that may wrap a date written as its own word: "(2026-03-12)."
_OPENERS, _CLOSERS = "([{\"'", ")]}\"'.,;:!?"
# source: ISO 8601-1:2019 §5.3.4 -- the minutes of a UTC offset are 00-59
_MAX_OFFSET_MINUTE = 59
# source: ISO 8601-1:2019 §5.2-§5.3: the components each written form states.
_PRECISION_BY_PARTS: dict[int, TemporalPrecision] = {
    2: "month",
    3: "day",
    5: "minute",
    6: "second",
}


def _offset(raw: str | None) -> timezone | None:
    """The stated UTC offset, or None when the source states no zone."""
    if raw is None:
        return None
    if raw == "Z":
        return timezone.utc
    digits = raw[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:])
    if minutes > _MAX_OFFSET_MINUTE:
        raise ValueError  # caught by stated_event_time: the time stays unknown
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(-delta if raw[0] == "-" else delta)


def _bound(parts: list[int], tz: timezone | None) -> TimeBound:
    """A TimeBound whose precision is the last component the source stated."""
    padded = parts + [1] * max(0, 3 - len(parts))
    value = datetime(*padded, tzinfo=tz)  # naive when the source names no zone
    return TimeBound(value=value, precision=_PRECISION_BY_PARTS[len(parts)])


def _is_own_word(sentence: str, m: re.Match[str]) -> bool:
    """False when the date sits inside a URL, a path or a file name."""
    before = re.split(r"\s", sentence[: m.start()])[-1]
    after = re.split(r"\s", sentence[m.end() :])[0]
    return not before.strip(_OPENERS) and not after.strip(_CLOSERS)


_Dated = tuple[re.Match[str], TimeBound]


def _iso_bounds(sentence: str) -> list[_Dated]:
    bounds = []
    for m in _ISO_RE.finditer(sentence):
        if not _is_own_word(sentence, m):
            continue
        parts = [int(g) for g in m.groups()[:6] if g is not None]
        bounds.append((m, _bound(parts, _offset(m.group(7)))))
    return bounds


def _named_bounds(sentence: str) -> list[_Dated]:
    bounds = []
    for m in _NAMED_RE.finditer(sentence):
        month = m["month"] or m["month_first"] or m["month_only"]
        day = m["day"] or m["day_second"]
        parts = [int(m["year"]), _MONTHS.index(month) + 1]
        bounds.append((m, _bound(parts + ([int(day)] if day else []), None)))
    return bounds


def _word_before(sentence: str, index: int) -> str:
    words = sentence[:index].split()
    return words[-1].strip(_OPENERS).lower() if words else ""


def _interval(sentence: str, dated: list[_Dated]) -> EventTime:
    """The interval one or two full dates and their framing words state.

    Any other shape is unknown. EventTime rejects an end before its start and
    a pair where one end alone states a zone (ValueError, caught by the caller).
    """
    if len(dated) == _CLOSED_ENDS:
        (m1, first), (m2, second) = dated
        gap = sentence[m1.end() : m2.start()].strip().lower()
        if (_word_before(sentence, m1.start()), gap) in _CLOSED_FRAMES:
            return EventTime(kind="interval", start=first, end=second)
    if len(dated) == 1:
        match, bound = dated[0]
        word = _word_before(sentence, match.start())
        if word in _OPEN_END_WORDS:
            return EventTime(kind="interval", start=bound)
        if word in _OPEN_START_WORDS:
            return EventTime(kind="interval", end=bound)
    return EventTime()


def stated_event_time(sentence: str) -> EventTime:
    """The event time a sentence states, or ``unknown`` when it states none.

    One distinct stated date is a ``point``; interval wording around full
    dates is an ``interval`` (see the module docstring). None, an impossible
    date ("2026-02-30"), several different ones outside an interval frame, or a
    ``sentence`` that holds more than one sentence leave the event time
    unknown. A date inside a URL, a path or a file name is not stated.
    """
    if "\n" in sentence or len(SENTENCE_END.split(sentence)) > 1:
        return EventTime()
    try:
        dated = sorted(
            _iso_bounds(sentence) + _named_bounds(sentence), key=lambda d: d[0].start()
        )
        if _RANGE_RE.search(sentence):
            return _interval(sentence, dated)
    except ValueError:  # an impossible date, offset or interval is not stated
        return EventTime()
    bounds = [b for _, b in dated]
    distinct = {(b.value, b.value.utcoffset(), b.precision): b for b in bounds}
    if len(distinct) != 1:
        return EventTime()
    return EventTime(kind="point", start=next(iter(distinct.values())))
