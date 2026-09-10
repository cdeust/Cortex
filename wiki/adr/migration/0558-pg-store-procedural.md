---
kind: adr
number: 0558
title: Preserve pg_store_procedural design decisions
status: accepted
---

# ADR-0558: pg_store_procedural design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_procedural.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — mined skill/habit persistence is its own concern,
distinct from prospective triggers/archives/engrams.

````

### upsert_procedural_skill, original line 19

````text
        On conflict the aggregate counters are set to the incoming values
        (the miner recomputes them from the full session history each run,
        so the newest mined figures are authoritative). Returns the row id.
        The action sequence is stored as a ``>``-joined string of step keys
        (``tool`` or ``tool:target_kind``), mirroring core.procedural_memory.
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
