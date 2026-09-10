---
kind: adr
number: 0591
title: Preserve pooled_sink design decisions
status: accepted
---

# ADR-0591: pooled_sink design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pooled_sink.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### comment, original line 19

````text
# A zero-arg callable returning a context manager that yields a psycopg
# connection (e.g. ``store.batch_pool.connection``). Injected so this layer
# never reaches into the store or psycopg_pool directly. The psycopg import is
# typing-only (TYPE_CHECKING) so this module loads in a SQLite-only install
# where the optional PostgreSQL driver is absent; the return type is a quoted
# forward reference so the alias evaluates without importing psycopg at runtime.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
