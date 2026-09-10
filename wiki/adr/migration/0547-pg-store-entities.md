---
kind: adr
number: 0547
title: Preserve pg_store_entities design decisions
status: accepted
---

# ADR-0547: pg_store_entities design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_entities.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### update_entities_heat_batch, original line 18

````text
        Source: issue #13 — mirror of update_memories_heat_batch for the
        entity decay path in consolidate.
        
````

### insert_entity, original line 49

````text
        If an entity with the same case-insensitive canonical name already
        exists, return its id (idempotent upsert). Otherwise insert with
        the canonicalized name. Source: Curie I4 audit (2026-04-16)
        found 111 case-variant duplicate groups; policy defined in
        `mcp_server/shared/entity_canonical.canonicalize_entity_name`.
        
````

### get_entity_by_name, original line 93

````text
        Looks up by LOWER(name) so callers don't need to know the
        canonical casing. Source: Curie I4 audit (2026-04-16).
        
````

### get_memories_mentioning_entity, original line 180

````text
Shared primitive with mixed callers. heads_only routes the read
        through the current_memories view (supersession chain heads only) on
        BOTH branches (FTS + ILIKE fallback): content-serving callers
        (get_causal_chain previews, assemble_context Phase 2) pass True.
        
````

### get_entity_ids_for_memories, original line 242

````text
        Source: refactor of ``recall_pipeline.dendritic_modulate`` to use
        real entity-set Jaccard (Jaccard 1912 set similarity) instead of
        the content-token proxy.
        
````

### comment, original line 67

````text
# ast_symbol is the safe superset: if any ingestion path says this
            # name is a code symbol, keep it exempt from fuzzy dedup forever.
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
