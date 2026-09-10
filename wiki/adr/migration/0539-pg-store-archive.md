---
kind: adr
number: 0539
title: Preserve pg_store_archive design decisions
status: accepted
---

# ADR-0539: pg_store_archive design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_archive.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of pg_store_auxiliary.py (issue #407: 397 lines over the
300-line §4.1 cap) — schema-mismatch archival is its own concern,
distinct from prospective/procedural/engram/cortical-schema storage.

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
