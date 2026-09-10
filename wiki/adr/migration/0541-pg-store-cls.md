---
kind: adr
number: 0541
title: Preserve pg_store_cls design decisions
status: accepted
---

# ADR-0541: pg_store_cls design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_cls.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_stats.py (issue #407: 406 lines over the
300-line §4.1 cap) — episodic/semantic CLS reads (McClelland 1995),
theta/gamma oscillatory-clock singleton state (Hasselmo 2005), and
interference detection (proactive/retroactive) are grouped here as the
"consolidation-adjacent read/write signals" concern, distinct from
cascade stage transitions (``pg_store_consolidation_stage``) and plain
counts/dashboard (``pg_store_stats``).

````

### get_episodic_memories, original line 76

````text
CLS input. Reads current_memories: the CLS clusters EVERY returned
        row (NOT is_stale does not cover supersession), so a superseded
        episodic version would be crystallized into a durable semantic fact.
        Chain heads carry the correction — consolidating heads only is the
        contract.
        
````

### get_semantic_memories, original line 102

````text
CLS dedup input. Reads current_memories: a superseded semantic row
        matching >0.85 cosine would otherwise suppress the creation of the
        corrected abstraction.
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
