---
kind: adr
number: 0563
title: Preserve pg_store_relationships design decisions
status: accepted
---

# ADR-0563: pg_store_relationships design decisions

## Context

Canonical migration of decision evidence from `mcp_server/infrastructure/pg_store_relationships.py` under ADR-0056.
The excerpts below preserve historical claims and citations verbatim; original ADR numbers are historical quotations, not current identity bindings.

## Decision

Keep the source implementation linked to this versioned decision record. Operational API documentation remains with the implementation.

## Preserved decision evidence

### update_relationships_weight_batch, original line 19

````text
        Source: issue #13 — plasticity LTP/LTD can update 30k+ edges in one
        cycle. Per-row UPDATEs dominate wall-clock on the consolidate run.
        
````

### delete_relationships_batch, original line 39

````text
        Source: issue #13 — pruning cycle deleted 32k+ edges per-row on
        darval's store.
        
````

### reinforce_or_create_relationship, original line 153

````text
        Phase 2 B3: collapses the pre-Phase-2 three-statement pattern
        (UPDATE fwd / UPDATE reverse / INSERT if both miss) into one
        INSERT ... ON CONFLICT DO UPDATE. For ``co_retrieval`` (a
        symmetric edge), ``(source_entity_id, target_entity_id)`` is
        canonicalized via LEAST/GREATEST so the UNIQUE partial index
        ``uq_relationships_canonical_co_retrieval`` fires correctly.
        Non-symmetric types (``causal``, etc.) keep the directional
        semantics and fall through the three-step legacy path because
        no UNIQUE constraint exists for them.
````

### reinforce_or_create_relationship, original line 153

````text
        Source: docs/program/phase-5-pool-admission-design.md (Phase 2
        B3 UPSERT); pg_schema.py migration for the UNIQUE constraint.
        
````

### comment, original line 54

````text
# Idempotent on the directed tuple (source, target, type). Re-ingest
        # (e.g. incremental codebase re-analysis) replays the same structural
        # edges; without ON CONFLICT this raises UniqueViolation on
        # uq_relationships_directed. On conflict we refresh the edge instead
        # of duplicating: keep the strongest weight, mark it re-reinforced.
        # Source: uq_relationships_directed (pg_schema.py §A3); issue #13.
````

### comment, original line 179

````text
# Touch entities: update last_accessed and warm heat on co-activation.
        # The +0.05 magnitude has no published or measured source: none —
        # engineering default, calibration pending (Cortex coding standard
        # §8). Same unsourced-+0.05-magnitude family as
        # core/reconsolidation.py:_RECONS_HEAT_BUMP_UPDATE (explicitly
        # labelled "calibration pending" there) and the wiki citation heat
        # bump (infrastructure/pg_schema.py WIKI_TRIGGERS_DDL, cfd8e4c3) —
        # internally consistent, not independently derived. See
        # docs/provenance/blend-weight-calibration.md for the procedural
        # precedent this codebase follows to graduate a placeholder like
        # this to a cited, measured value (that document itself does not
        # cover this constant).
````

## Consequences

Review rationale and source changes together. Historical evidence is preserved rather than silently rewritten; executable Python structure is unchanged after removing docstrings.
