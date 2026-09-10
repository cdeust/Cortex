---
kind: adr
number: 0507
title: Preserve brain_index_store design decisions
status: accepted
---

# ADR-0507: brain_index_store design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/brain_index_store.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
- load_brain_index always returns a valid structure (never None)

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
