---
kind: adr
number: 0543
title: Preserve pg_store_consolidation_stage design decisions
status: accepted
---

# ADR-0543: pg_store_consolidation_stage design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_consolidation_stage.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_stats.py (issue #407: 406 lines over the
300-line §4.1 cap) — the LABILE→EARLY_LTP→LATE_LTP→CONSOLIDATED
cascade's stage writes/reads (Kandel 2001) are their own concern,
distinct from counts/dashboard (``pg_store_stats``) and CLS/
oscillatory/interference queries (``pg_store_cls``).

````

### insert_stage_transitions_batch, original line 37

````text
        Source: issue #13 — was per-row INSERT + per-row commit inside the
        cascade loop (503 fsyncs on darval's run).
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
