---
kind: adr
number: 0612
title: Preserve sqlite_store_queries design decisions
status: accepted
---

# ADR-0612: sqlite_store_queries design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/sqlite_store_queries.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### get_all_memories_for_validation, original line 112

````text
        Mirrors PgQueryMixin.get_all_memories_for_validation — see there
        for the cursor/include_stale rationale.
        
````

### iter_memories_for_decay, original line 172

````text
        PG streams chunks through a server-side cursor because its corpora
        reach 500k+ rows; SQLite serves the local plugin install, where the
        corpus fits in memory and the store already materializes it for
        every other decay path. One yielded chunk therefore matches
        PgMemoryStore's own ``POOL_DISABLED`` compatibility path exactly.
        ``chunk_size`` is accepted for signature parity and unused.
        
````

### delete_memories_by_tag, original line 209

````text
        precondition: tag is a non-empty string; domain is None or a non-empty string.
        postcondition: returns the number of memory rows removed; rows removed
            iff their tags list contains tag AND (domain is None OR row.domain
            matches). domain=None preserves the legacy global-purge behavior.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
