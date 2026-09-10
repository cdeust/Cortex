---
kind: adr
number: 0562
title: Preserve pg_store_receipts design decisions
status: accepted
---

# ADR-0562: pg_store_receipts design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_receipts.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Blame path T1/T2/T3 (decision Cortex 4255039): receipts are an
append-only record of what a channel injected into a context — there is
no update or delete surface by design. T3 adds the read path: resolving
receipt ids (handed back by the model from ⟦rcpt:id⟧ context markers)
into presence-in-context evidence.
````

### fetch_injection_receipts, original line 109

````text
        One row per injected memory, ordered by recorded facts only
        (emitted_at DESC, receipt id DESC, persisted rank ASC). Unknown
        ids simply yield no rows — the handler reports them; an empty
        input reads as an empty result (the loud non-empty contract
        lives at the tool boundary, not here).
        
````

### comment, original line 22

````text
# Single data-modifying-CTE statement on purpose: the store's
# ``_execute`` borrows a pool connection per call, so two separate
# INSERTs could land on two connections and lose header/items atomicity.
````

### comment, original line 69

````text
# Read path (T3). LEFT JOIN on purpose: memory_id carries no FK — a
# memory hard-forgotten after injection must NOT erase the evidence that
# it WAS in context; such rows come back with every m.* column NULL.
# superseded_by_id is surfaced, never filtered: a receipt is historical
# evidence, and a superseded memory that was injected stays part of the
# record — the caller sees the correction state instead. Ordering is
# recorded facts only (decision 4255039): emitted_at DESC, receipt id
# DESC as the deterministic tiebreak, then the persisted injection rank.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
