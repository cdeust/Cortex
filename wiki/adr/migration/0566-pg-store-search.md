---
kind: adr
number: 0566
title: Preserve pg_store_search design decisions
status: accepted
---

# ADR-0566: pg_store_search design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_search.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — every method here delegates to a PL/pgSQL stored procedure or a
single read-only SELECT; grouped together because they are the primary
"read path" concern, as opposed to the write-path (``pg_store_write``),
metadata-mutation (``pg_store_heat`` / ``pg_store_memory_meta``), and
downstream-signal (``pg_store_signals`` — spreading activation,
Hopfield embeddings, temporal co-access; split out separately after
the #399 trust-term port pushed this file to 301 lines) mixins.

````

### _run_recall, original line 92

````text
        See ``_recall_bind_params`` for the bind-order contract.
        
````

### recall_memories, original line 132

````text
        ``trusted_origins``/``untrusted_factor`` (issue #368): passed in,
        not imported (infra may not depend on core; caller reads them from
        ``core/capture_origin.py``). Defaults are the identity transform.
        
````

### search_fts, original line 158

````text
        Reads current_memories + NOT is_stale: this is a discovery channel
        whose hits are injected by callers (prospective triggers) with a
        fabricated score ABOVE the ranked results — exclusion must happen
        here, no downstream ranking can demote a superseded or stale hit.
        
````

### search_vectors, original line 182

````text
        heads_only routes through the current_memories view (supersession
        chain heads only): the write-gate novelty helpers pass True so a
        reformulation of an already-corrected fact is not scored "not novel"
        against the dead version. Default stays False — interference/
        forgetting callers must keep seeing physical rows.
        
````

### comment, original line 67

````text
# issue #368 — the trust policy is passed IN, never imported:
            # infrastructure must not depend on core (module-inventory.md
            # dependency rules). It travels from the caller to the stored
            # procedure on every call, so neither this layer nor the SQL
            # holds a second copy of the vocabulary that could drift.
````

### comment, original line 112

````text
# created_at must be ISO text, not datetime -- see
        # _isoformat_datetime_fields's docstring (mixed-type candidate lists).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
