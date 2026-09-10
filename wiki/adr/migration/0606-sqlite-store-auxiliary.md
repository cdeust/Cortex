---
kind: adr
number: 0606
title: Preserve sqlite_store_auxiliary design decisions
status: accepted
---

# ADR-0606: sqlite_store_auxiliary design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_store_auxiliary.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### count_memories_in_slot, original line 197

````text
        Lightweight alternative to ``get_memories_in_slot`` when only the
        count is needed (e.g. the ``temporally_linked`` metric in engram
        allocation).  *exclude_id* omits a specific memory from the count
        so the caller doesn't need to guess whether it's committed yet.
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
