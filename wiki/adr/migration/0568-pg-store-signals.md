---
kind: adr
number: 0568
title: Preserve pg_store_signals design decisions
status: accepted
---

# ADR-0568: pg_store_signals design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_signals.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_search.py (issue: the trust/provenance-term port
from #399 pushed the file to 301 lines, one over the 300-line §4.1
cap) — spreading activation, Hopfield/HDC embedding fetches, and the
temporal co-access graph feed are downstream consumers of a recall
result, not the recall/FTS/vector-search primitives themselves.

````

### spread_activation_memories, original line 31

````text
        domain/include_globals scope the final entity->memory mapping to
        one cognitive domain (plus is_global rows when include_globals is
        True) -- mirrors recall_memories()'s p_domain/p_include_globals.
        domain=None (default) disables the filter -- see the PL/pgSQL
        function's docstring in pg_schema.py for why callers must pass
        an explicit domain (ADR-0054: measured 52.8% cross-domain
        injection when unscoped).
        
````

### get_embeddings_for_memories, original line 81

````text
        NULL embeddings are filtered out — Hopfield can't use them.
        Source: refactor of ``recall_pipeline.hopfield_complete`` to
        bound PG round-trips at top_k=30.
        
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
