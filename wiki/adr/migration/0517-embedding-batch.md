---
kind: adr
number: 0517
title: Preserve embedding_batch design decisions
status: accepted
---

# ADR-0517: embedding_batch design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/embedding_batch.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
The consolidation writers already isolate encoding/storage failures per item.
Preserve that contract: after a logged whole-batch failure, retry each input
through scalar encode, retaining individual errors for the caller's existing
boundary. No core imports, store calls, model construction or new batch limit.

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
