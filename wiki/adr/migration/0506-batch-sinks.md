---
kind: adr
number: 0506
title: Preserve batch_sinks design decisions
status: accepted
---

# ADR-0506: batch_sinks design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/batch_sinks.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Both implement the ``BatchSink`` contract — one batch in, durably committed,
released — and are atomic per batch via ``with conn.transaction()`` (the only
construct that gives BEGIN/COMMIT/ROLLBACK under ``autocommit=True``).
````

### comment, original line 48

````text
# atomic per batch under autocommit
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
