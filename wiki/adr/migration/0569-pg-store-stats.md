---
kind: adr
number: 0569
title: Preserve pg_store_stats design decisions
status: accepted
---

# ADR-0569: pg_store_stats design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_stats.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Cascade stage transitions live in the sibling ``pg_store_consolidation_stage``
module and CLS/oscillatory/interference queries in ``pg_store_cls`` (both
split out by issue #407: this file was 406 lines over the 300-line §4.1 cap).

````

### signature_repeat_stats, original line 43

````text
        Returns ``(repeat_count, hours_since_last)`` for memories sharing this
        normalised ``stimulus_signature`` — the count feeds the write gate's
        response decrement (Rankin 2009) and the elapsed hours drive
        spontaneous recovery. ``hours_since_last`` is None when the signature is
        unseen. Best-effort: returns ``(0, None)`` on any error or when the
        column is absent (a store predating habituation), so the gate treats an
        un-migrated store as if nothing has habituated.
        
````

### _grooming_tag_prefix_age, original line 134

````text
        The 'lesson' prefilter is semantically required (curate_distill.py
        and lesson_promotion.py both only ever tag their output 'lesson',
        so it cannot exclude a true positive) and index-backed
        (idx_memories_tags_gin); measured 18-23ms worst case (zero
        matching rows -- the only state observed so far, 2026-07-11),
        collapsing to sub-ms once any row matches.
        
````

### get_grooming_ages, original line 154

````text
        Precondition: none.
        Postcondition: returns {"wiki", "distillation", "promotion"} ->
        ISO-8601 timestamp of the most recent judgment-level action of
        that kind, or None if that kind has never executed in this
        store. Read-only. wiki: MAX(wiki.pages.tended) -- ~0.4ms at 154
        rows (EXPLAIN ANALYZE, 2026-07-11; no dedicated index needed at
        this table size, sequential scan). distillation/promotion: see
        ``_grooming_tag_prefix_age``.
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.

### signature_repeat_stats: completeness audit

````text
Habituation (E1) read side: prior presentations of a stimulus.

Returns ``(repeat_count, hours_since_last)`` for memories sharing this
        normalised ``stimulus_signature`` — the count feeds the write gate's
        response decrement (Rankin 2009) and the elapsed hours drive
        spontaneous recovery. ``hours_since_last`` is None when the signature is
        unseen.

source: ADR-0569
````

### extinguished_count: completeness audit

````text
Extinction (E2) read side: count of deprecated-but-retained memories.

Returns how many memories carry an inhibitory extinction tag at or above
``threshold`` — the association is suppressed WITHOUT deletion (the row
is fully present, not is_stale), so it can spontaneously recover or be
reinstated (Bouton 2004). Best-effort: returns 0 on any error or when
the ``extinction_strength`` column is absent (a store predating
extinction), so an un-migrated store reports nothing extinguished.
````
