---
title: "ADR-0671 — mcp_server/shared/temporal_timezones.py rationale"
status: accepted
source: mcp_server/shared/temporal_timezones.py
---

# ADR-0671 — mcp_server/shared/temporal_timezones.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
`dateutil.parser.parse` drops a timezone abbreviation it cannot resolve and
returns a *naive* datetime. Every downstream reader then reads that naive
value as UTC (`temporal.compute_recency_boost`, PostgreSQL's `timestamptz`
cast), so `13:56 EST` is persisted as `13:56+00:00` — five hours off, with
nothing emitted (issue #252).
````

## module — original line 9 (docstring)

````text
This module supplies the `tzinfos` resolver that closes the hole: a stated
abbreviation either resolves through a cited table, or the caller is told the
name it could not resolve so it can refuse the value. The zone is never
dropped.
````

## module — original line 14 (docstring)

````text
The alternative fix — wrapping the parse in `warnings.catch_warnings()` and
promoting dateutil's `UnknownTimezoneWarning` to an error — mutates
process-global filter state and is documented as not thread-safe; on a store
write path that is worse than the defect it closes.
````

## module — original line 19 (docstring)

````text
Pure business logic -- no I/O.

````

## RFC5322ZoneResolver — original line 64 (docstring)

````text
    * returns an already-resolved numeric offset unchanged — that covers
      `+02:00`, `UTC`, `GMT` and `Z`, which dateutil hands over as offset 0;
    * resolves an RFC 5322 §4.3 abbreviation to its offset;
    * records any other abbreviation in `unresolved` and returns None.
````

## RFC5322ZoneResolver — original line 69 (docstring)

````text
    Returning None makes dateutil build a naive datetime, so a caller MUST
    check `unresolved` after the parse and refuse the value. That check is
    what turns a dropped zone into a refusal instead of a silent re-anchor.
````

## module — original line 24 (comment)

````text
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
````

## module — original line 50 (comment)

````text
# source: SI derived unit — 1 h = 60 min x 60 s.
````
