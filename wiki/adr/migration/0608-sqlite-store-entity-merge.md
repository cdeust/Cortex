---
kind: adr
number: 0608
title: Preserve sqlite_store_entity_merge design decisions
status: accepted
---

# ADR-0608: sqlite_store_entity_merge design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_store_entity_merge.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### SqliteEntityMergeMixin, original line 18

````text
Atomic entity collapse on SQLite.
````

### comment, original line 13

````text
# source: structural — the id-lookup fetches exactly the survivor + alias pair
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
