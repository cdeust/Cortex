---
kind: adr
number: 0613
title: Preserve sqlite_store_receipts design decisions
status: accepted
---

# ADR-0613: sqlite_store_receipts design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_store_receipts.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Blame path T1/T3 (decision Cortex 4255039): append-only record of what
a channel injected into a context, plus the T3 read path resolving
receipt ids into presence-in-context evidence. PG parity with
pg_store_receipts.py.

````

### fetch_injection_receipts, original line 60

````text
        PG parity with ``PgReceiptsMixin.fetch_injection_receipts``:
        LEFT JOIN keeps evidence rows whose memory was hard-forgotten
        after injection (every m.* column NULL); superseded memories are
        surfaced with their correction state, never filtered; ordering
        replays recorded facts only (emitted_at is ISO text, so DESC is
        chronological). Empty input reads as empty output — the loud
        non-empty contract lives at the tool boundary.
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
