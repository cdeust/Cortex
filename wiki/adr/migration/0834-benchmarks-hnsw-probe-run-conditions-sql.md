---
title: "ADR-0834 — benchmarks/hnsw_probe/run_conditions.sql rationale"
status: accepted
source: benchmarks/hnsw_probe/run_conditions.sql
---

# ADR-0834 — benchmarks/hnsw_probe/run_conditions.sql

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## benchmarks/hnsw_probe/run_conditions.sql — original line 13

````text
-- Measurement: server-side clock_timestamp() deltas. No psycopg/round-trip noise.
-- This is strictly a LOWER bound on production cost (prod has network+python overhead).
-- If HNSW signal is strong here, it's strong in prod.
````

## benchmarks/hnsw_probe/run_conditions.sql — original line 17

````text
-- Gating: each replicate uses a unique delta so every UPDATE changes the heat value.
-- This ensures we never hit an IS DISTINCT FROM no-op by accident.
````

## benchmarks/hnsw_probe/run_conditions.sql — original line 124

````text
-- Helper to keep heat values bounded: normalize heat back into a tight band
-- (we don't want heat to drift across many replicates and saturate).
````

## benchmarks/hnsw_probe/run_conditions.sql — original line 134

````text
-- Helper to drop / recreate HNSW (used between conditions).
-- Drop: instant. Create: ~100s on 66K rows (measured in setup).
-- We'll cache this by running WITH-HNSW conditions consecutively, then WITHOUT.
````

## Final non-Python residual audit

### benchmarks/hnsw_probe/run_conditions.sql — pre-cleanup line 10

````text
-- Plus probe F) HNSW present, per-row UPDATE with per-row COMMIT
--             (matches production exactly)  — only measure once due to runtime.
````
