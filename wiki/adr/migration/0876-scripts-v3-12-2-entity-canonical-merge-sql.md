---
title: "ADR-0876 — scripts/v3_12_2_entity_canonical_merge.sql rationale"
status: accepted
source: scripts/v3_12_2_entity_canonical_merge.sql
---

# ADR-0876 — scripts/v3_12_2_entity_canonical_merge.sql

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## scripts/v3_12_2_entity_canonical_merge.sql — original line 1

````text
-- scripts/v3_12_2_entity_canonical_merge.sql
-- ============================================================================
-- Cortex v3.12.2 — Entity Case-Variant Dedup Migration
-- Source: Curie I4 completeness audit (2026-04-16)
-- Spec: mcp_server/shared/entity_canonical.py (canonicalize_entity_name policy)
````

## scripts/v3_12_2_entity_canonical_merge.sql — original line 7

````text
-- Problem (pre-migration):
--   Entity extraction did not case-canonicalize names at insert time, so
--   `Output` and `OUTPUT` and `output` all created separate rows.
--   Curie audit found 111 duplicate groups across 196 entity rows.
````

## scripts/v3_12_2_entity_canonical_merge.sql — original line 22

````text
-- Safety:
--   - Wrapped in a single BEGIN/COMMIT so partial failure rolls back.
--   - ON CONFLICT DO NOTHING guards the composite PK constraints.
--   - Pre-verification count + post-verification zero-duplicates assertion.
--   - Idempotent: re-running after success is a no-op.
````
