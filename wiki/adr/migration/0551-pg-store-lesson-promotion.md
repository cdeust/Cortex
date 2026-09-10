---
kind: adr
number: 0551
title: Preserve pg_store_lesson_promotion design decisions
status: accepted
---

# ADR-0551: pg_store_lesson_promotion design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_lesson_promotion.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Mirrors ``pg_store_wiki_notes.py::list_uncited_deliberate_memories`` —
same ``current_memories`` view, same read-only contract: this module
never writes a rule, a trigger, a page, or a tag. It lists candidates for
``handlers.lesson_promotion`` to package into jobs, exactly as
``curate_wiki_uncited.py`` lists candidates for wiki authoring.

````

### list_lesson_promotion_candidates, original line 41

````text
List active lesson/lesson-candidate memories with usage evidence.
````

### list_lesson_promotion_candidates, original line 41

````text
    Precondition: none — works on any schema-provisioned DB, even with
    zero lesson-tagged rows.
    Postcondition: returns memories tagged 'lesson' or 'lesson-candidate',
    not stale, not already carrying a 'promoted:*' tag, with
    access_count > 0 OR useful_count > 0 (at least one real recall
    surfacing or rating event — a structural zero/nonzero boundary, not
    a tuned magnitude threshold), ordered by useful_count then
    access_count descending so the most-validated lessons surface
    first. Read-only: never mutates memory_rules, prospective_memories,
    wiki.citations, or the memories table itself.
    
````

### count_lesson_promotion_candidates, original line 68

````text
    Precondition: same as ``list_lesson_promotion_candidates``.
    Postcondition: returns the exact row count matching
    ``_ELIGIBLE_WHERE`` — the same eligibility definition
    ``list_lesson_promotion_candidates`` uses, just without a ``LIMIT``
    truncating it. Read-only, single indexed ``COUNT(*)`` (measured
    ~76ms against a 154-page / 3000+ memory dev corpus, 2026-07-11) —
    cheap enough for a per-consolidate-cycle mechanical report — and
    down to ~0.8ms Bitmap Heap Scan with idx_memories_tags_gin
    (pg_schema.py; EXPLAIN ANALYZE 2026-07-11, 11,012 rows) — unlike
    ``curate_distill``'s clustering-derived backlog count (measured
    ~2.6s on the same corpus; see wiki_backlog_pass.py's docstring for
    why that one is NOT wired into the recurring cycle).
    
````

### comment, original line 20

````text
# Shared by both queries below so the eligibility definition cannot drift
# between the job-listing path and the count-only path (G-2 grooming:
# count_lesson_promotion_candidates reuses this verbatim rather than
# re-deriving an equivalent WHERE clause that could silently disagree).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
