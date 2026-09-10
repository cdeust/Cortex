---
title: "ADR-0877 — scripts/v3_13_0_a3_migration.sql rationale"
status: accepted
source: scripts/v3_13_0_a3_migration.sql
---

# ADR-0877 — scripts/v3_13_0_a3_migration.sql

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## scripts/v3_13_0_a3_migration.sql — original line 5

````text
-- Source: docs/program/phase-3-a3-migration-design.md §1 (schema migration).
-- Invariants: I1 (heat ∈ [0,1]), I2 (one canonical writer), I5 (stage decay
-- exponents in effective_heat), I10 (still applies at pool layer).
````

## scripts/v3_13_0_a3_migration.sql — original line 9

````text
-- What this DDL does:
--   1. Rename memories.heat → memories.heat_base + add CHECK bounds.
--   2. Add memories.heat_base_set_at (provenance timestamp for the bump).
--   3. Add memories.no_decay (anchor + import-pin flag).
--   4. Create homeostatic_state table (one row per domain, scalar factor).
--   5. Monthly RANGE partition memories on created_at (Thompson D1).
--   6. Per-partition HNSW / GIN / B-tree indexes (pgvector #875 mitigation).
--   7. ensure_memory_partition_for() helper for auto-creation.
````

## scripts/v3_13_0_a3_migration.sql — original line 88

````text
-- Seed default per-domain rows discovered from memories. Readers MUST
-- still COALESCE((SELECT factor FROM homeostatic_state WHERE domain=…), 1.0)
-- because new domains arriving between seed and first homeostatic run
-- would otherwise miss their row.
````

## scripts/v3_13_0_a3_migration.sql — original line 124

````text
-- Pre-create 12 partitions from current month forward + 1 historical.
````

## scripts/v3_13_0_a3_migration.sql — original line 137

````text
-- Historical catch-all for pre-current-month data. Keeps all darval-era
-- memories queryable without rewriting them into monthly partitions.
````

## scripts/v3_13_0_a3_migration.sql — original line 151

````text
-- ----------------------------------------------------------------------------
-- 1.5 Per-partition indexes. Smaller indexes = faster UPDATE maintenance.
-- pgvector #875 mitigation: HNSW re-insert cost scales with partition size,
-- not total store. B-tree(heat_base) preserves ORDER BY usability for
-- the recall hot CTE post-A3.
-- ----------------------------------------------------------------------------
````

## scripts/v3_13_0_a3_migration.sql — original line 186

````text
-- ----------------------------------------------------------------------------
-- 1.6 Auto-create next month's partition on demand. Called at start of
-- consolidate so no cron needed.
-- ----------------------------------------------------------------------------
````

## Final non-Python residual audit

### scripts/v3_13_0_a3_migration.sql — pre-cleanup line 27

````text
--   - INSERT INTO copy of memories → partitioned memories; tested on
--     darval-scale 66K in ~4 minutes per spec §1.3.
````

### scripts/v3_13_0_a3_migration.sql — pre-cleanup line 68

````text
-- Back-populate heat_base_set_at from last_accessed (Lamport §3: the last
-- known causal touch is our best proxy for when heat_base was last valid).
````

### scripts/v3_13_0_a3_migration.sql — pre-cleanup line 79

````text
-- Feynman: heat is a function, not a state — the cycle adjusts a scalar.
````

### scripts/v3_13_0_a3_migration.sql — pre-cleanup line 99

````text
-- 1.4 Monthly RANGE partition on memories.created_at (Thompson D1).
-- Strategy: rename memories → memories_pre_a3, create new partitioned
-- memories with IDENTICAL schema, INSERT INTO to copy data, drop old.
-- For stores < 1M rows this finishes in ≤5 min per spec §1.3.
````

## Final non-Python residual audit

### scripts/v3_13_0_a3_migration.sql — pre-cleanup line 18

````text
-- What this DDL does NOT do (that's steps 2-8 of the spec):
--   - Add effective_heat() function (step 2 lands that in pg_schema.py).
--   - Rewrite recall_memories() (step 6).
--   - Delete decay_memories() (step 7).
--   - Flip the A3_LAZY_HEAT flag (step 9).
````
