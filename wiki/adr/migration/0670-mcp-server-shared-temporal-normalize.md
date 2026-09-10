---
title: "ADR-0670 — mcp_server/shared/temporal_normalize.py rationale"
status: accepted
source: mcp_server/shared/temporal_normalize.py
---

# ADR-0670 — mcp_server/shared/temporal_normalize.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Separate from `temporal.py`, which scores dates for retrieval: the two have
different reasons to change. Scoring answers "how close is this date to the
query?" and may drop precision freely; storage normalization answers "which
instant does this string denote?" and may not — a dropped timezone is read as
UTC by every downstream consumer (PostgreSQL's `timestamptz` cast,
`temporal.compute_recency_boost`), so it silently persists the wrong instant
(issue #252).
````

## module — original line 11 (docstring)

````text
Pure business logic -- no I/O.

````

## normalize_date_to_iso — original line 56 (docstring)

````text
    Handles formats like '1:56 pm on 8 May, 2023' (LoCoMo),
    '8 May 2023', 'May 8, 2023', ISO strings, and other common formats.
    Falls back to dateutil for complex formats with time components.
````

## normalize_date_to_iso — original line 60 (docstring)

````text
    A stated timezone is honoured or the value is refused: an abbreviation
    outside the RFC 5322 §4.3 table (see `temporal_timezones`) is never
    dropped, because a dropped zone reads as UTC everywhere downstream.
````

## module — original line 28 (comment)

````text
# A complete ISO 8601 date-time of day, which is stored verbatim.
# source: ISO 8601-1:2019 §5.4.2 (<date>T<time> combination) with the §4.3.13
# UTC designator / §4.3.14 offset optional. Anchored at both ends: a substring
# test ("T" in raw) matched any string merely CONTAINING a capital T — every
# US zone abbreviation does ("EST", "PST", "CST", "MST") — and returned it
# unparsed (issue #252).
````

## module — original line 38 (comment)

````text
# A time of day anywhere in the string. `parse_date` reads the date and
# discards whatever follows it, so on a string that states a time (and
# possibly a zone) that fast path would silently move the instant to midnight.
````

## module — original line 43 (comment)

````text
# A timezone the string STATES: a trailing numeric UTC offset, or the trailing
# 2-5 letter uppercase abbreviation shape of RFC 5322 §4.3's obs-zone. Matched
# structurally, not resolved: this only has to answer "did the producer state a
# zone?", so that a value whose zone could not be APPLIED is refused instead of
# salvaged. Salvaging it would return a naive date, and a naive date is read as
# UTC by every consumer — the defect of issue #252, reintroduced through the
# degraded path.
````

## inline — original line 82 (directive-rationale)

````text
# noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
````
