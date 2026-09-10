---
kind: adr
number: 0573
title: Preserve pg_store_wiki_claims design decisions
status: accepted
---

# ADR-0573: pg_store_wiki_claims design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_wiki_claims.py` under ADR-0056.
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

### insert_claim_events, original line 26

````text
    Each ``claims`` dict requires: ``text``, ``claim_type``. Optional:
    memory_id, session_id, entity_ids, evidence_refs, confidence,
    supersedes, embedding (vector or None).
````

### get_entity_name_index, original line 114

````text
    Limit caps the index size for in-memory matching against claim text.
    Heat-ranked so the most frequently-touched entities win.
    
````

### get_claims_by_entity, original line 141

````text
    Used by the resolver to find supersedes / conflict candidates.
    Excludes the claims being resolved (avoid self-matches).
    
````

### update_claim_supersedes, original line 198

````text
Bulk update wiki.claim_events.supersedes. Returns rows updated.
````

### update_claim_supersedes, original line 198

````text
    ``updates`` is [(new_claim_id, superseded_claim_id), ...].
    
````

### comment, original line 108

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
