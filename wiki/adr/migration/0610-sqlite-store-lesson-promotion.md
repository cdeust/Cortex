---
kind: adr
number: 0610
title: Preserve sqlite_store_lesson_promotion design decisions
status: accepted
---

# ADR-0610: sqlite_store_lesson_promotion design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_store_lesson_promotion.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
SQLite twin of ``pg_store_lesson_promotion.count_lesson_promotion_
candidates`` -- same ``current_memories`` view, same eligibility
semantics, same read-only contract. A separate module (not a branch in
the PG one) because the PG SQL is untranslatable mechanically: ``@>``
and ``jsonb_array_elements_text`` have no SQLite equivalent, and the
psycopg-compat wrapper deliberately translates only lexical conventions
(sqlite_compat.py's translation table), never jsonb operators. The
composition root (handlers/get_grooming_health.py) dispatches on the
store type.

````

### list_lesson_promotion_candidates, original line 42

````text
    Exists because ``handlers/lesson_promotion.py`` called the PG function
    unconditionally, so the handler raised
    ``sqlite3.OperationalError: unrecognized token: "@"`` on the SQLite
    backend — which is the plugin default. ``LEFT(...)`` is PG-only;
    ``substr(...,1,500)`` is the SQLite spelling of the same truncation
    (issue #220).
    
````

### comment, original line 20

````text
# Same eligibility definition as pg_store_lesson_promotion._ELIGIBLE_WHERE,
# expressed with json_each: not stale, tagged 'lesson' or
# 'lesson-candidate', at least one recall/rating event, and no
# 'promoted:*' tag yet. Kept as one shared constant for the same
# anti-drift reason as the PG twin.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
