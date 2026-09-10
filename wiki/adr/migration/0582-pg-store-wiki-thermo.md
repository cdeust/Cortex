---
kind: adr
number: 0582
title: Preserve pg_store_wiki_thermo design decisions
status: accepted
---

# ADR-0582: pg_store_wiki_thermo design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_wiki_thermo.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### module, original line 1

````text
Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.
````

### list_pages_for_decay, original line 26

````text
    Skips evergreen by default (never decays) and archived unless
    ``include_archived`` is True (only useful to detect revivals,
    which we handle via the citation trigger anyway).
    
````

### get_claim_file_refs_for_pages, original line 105

````text
For each page, return the file paths cited by its source memory's claims.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
