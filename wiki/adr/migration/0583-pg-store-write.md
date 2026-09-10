---
kind: adr
number: 0583
title: Preserve pg_store_write design decisions
status: accepted
---

# ADR-0583: pg_store_write design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_write.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — the single-writer INSERT path: SQL constant + param building +
the two commit strategies (``insert_memory`` commits standalone;
``_insert_memory_on`` leaves the transaction boundary to its caller).
Atomic reconsolidation-supersession (which reuses ``_insert_memory_on``
inside its own transaction) is a separate concern — see the sibling
``pg_store_supersede`` module.

````

### _resolve_insert_dates, original line 64

````text
        A3 decay clock: anchor heat_base_set_at to the event date, not NOW().
        effective_heat() decays from COALESCE(heat_base_set_at, last_accessed,
        created_at); for a never-touched insert the faithful "last canonical
        touch" IS the event (created_at), so a historical-dated memory
        (import / benchmark loader) engages the SQL forgetting law instead of
        reading hours_elapsed≈0. No-op for fresh writes where created_at≈now.
        Source: docs/program/phase-3-a3-migration-design.md §3.1 (clock = last
        touch); benchmark root-cause memory 4202968.
````

### _resolve_insert_dates, original line 64

````text
        No "is it already ISO?" pre-test here: deciding that is
        normalize_date_to_iso's job, and it returns a real ISO datetime
        unchanged. The pre-test this replaces was `"T" not in raw_created`,
        which skipped normalization for every string merely CONTAINING a T —
        including "8 May 2023 13:56 EST" (issue #252).
````

### _insert_memory_on, original line 171

````text
        The caller owns the transaction boundary: insert_memory() commits on a
        pooled autocommit connection; supersede_atomic() commits or rolls back
        the row together with its supersession edge.
        
````

### comment, original line 28

````text
# Single source of truth for the memory INSERT. insert_memory() runs it on
    # a pooled autocommit connection (one row per statement); supersede_atomic()
    # runs it inside an explicit transaction so the row and its supersession
    # edge commit — or roll back — as one unit, never leaving a disconnected row.
````

### comment, original line 138

````text
# issue #365: channel-derived capture origin. Defaults to
            # "unknown" (permissive at the gate) so every existing writer
            # is unaffected; the auto-capture path passes its real origin.
````

### comment, original line 144

````text
# M-D2 (7.4): every writer resolves this explicitly BEFORE
            # calling insert_memory (mcp_server.shared.write_class is the
            # single classification choke point; infrastructure/ must not
            # import core/, so this layer trusts the caller and relies on
            # the memories.write_class CHECK constraint as the DB-level
            # backstop against a value outside the four known classes).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
