---
kind: adr
number: 0571
title: Preserve pg_store_wiki design decisions
status: accepted
---

# ADR-0571: pg_store_wiki design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_wiki.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Wiki schema DB operations (Phase 1 of redesign).
````

### module, original line 1

````text
Files on disk remain the source of truth for wiki.pages; this module
maintains the query index. All writes are idempotent (UPSERT by rel_path
or body_hash). Triggers on wiki.links and wiki.citations maintain the
denormalised counters on wiki.pages.
````

### module, original line 1

````text
This module is now a thin re-export facade: the implementation was split
across sibling ``pg_store_wiki_*`` modules (pages / links / claims /
thermo / concepts / drafts / notes / common) to satisfy the 300-line
file limit (CLAUDE.md "Code Quality Rules") — originally 890 lines.
Every name below is re-exported verbatim so existing importers
(``from mcp_server.infrastructure.pg_store_wiki import X``) keep working
unchanged. No logic changed.

````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
