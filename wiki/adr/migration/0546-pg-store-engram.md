---
kind: adr
number: 0546
title: Preserve pg_store_engram design decisions
status: accepted
---

# ADR-0546: pg_store_engram design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_engram.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — engram slot allocation (Josselyn & Tonegawa 2020)
is its own concern, distinct from prospective/procedural/archive/
cortical-schema storage.

````

### count_memories_in_slot, original line 79

````text
        Lightweight alternative to ``get_memories_in_slot`` when only the
        count is needed (e.g. the ``temporally_linked`` metric in engram
        allocation).  *exclude_id* omits a specific memory from the count
        so the caller doesn't need to guess whether it's committed yet.
        
````

### comment, original line 25

````text
# source: PostgreSQL 16 functions-srf.html / sql-insert.html.
        # Preserve the existing range, excitability and conflict behavior;
        # the first remember previously sent 5000 independent INSERTs.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
