---
kind: adr
number: 0544
title: Preserve pg_store_cortical_schema design decisions
status: accepted
---

# ADR-0544: pg_store_cortical_schema design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_cortical_schema.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — named ``cortical_schema`` (not ``schema``) to avoid
colliding with ``pg_store_ddl.py``'s unrelated database-DDL "schema"
vocabulary; this is the cognitive-science sense (schema_engine.py).

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
