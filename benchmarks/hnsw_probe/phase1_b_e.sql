-- Phase 1 (HNSW present): conditions B and E — batched UPDATEs.
-- Expected to be fast (seconds each).

SET client_min_messages = WARNING;
\pset format unaligned

-- Confirm HNSW still present.
SELECT 'hnsw_present' AS flag, COUNT(*) FROM pg_indexes
WHERE tablename = '_bench_memories_hnsw' AND indexname LIKE '%hnsw%';

-- ── Condition B: HNSW + batched UNNEST UPDATE ──
SELECT _bench_reset_heat();
SELECT 'warmup_b' AS label, * FROM _bench_batched_update(0.00021);

-- Replicate 1
SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'B', 1, 'measure', elapsed_ms, rows_updated, 'HNSW+batched'
FROM _bench_batched_update(0.00022);

-- Replicate 2
SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'B', 2, 'measure', elapsed_ms, rows_updated, 'HNSW+batched'
FROM _bench_batched_update(0.00023);

-- Replicate 3
SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'B', 3, 'measure', elapsed_ms, rows_updated, 'HNSW+batched'
FROM _bench_batched_update(0.00024);

-- ── Condition E: HNSW + batched UPDATE with IS DISTINCT FROM gating ──
-- Since we reset heat to random before each run, every row is distinct, so
-- gating will NOT reduce row count here. It tests the gating overhead when
-- all rows actually change.
SELECT _bench_reset_heat();
SELECT 'warmup_e' AS label, * FROM _bench_batched_update_gated(0.00031);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'E', 1, 'measure', elapsed_ms, rows_updated, 'HNSW+batched+gated(allchange)'
FROM _bench_batched_update_gated(0.00032);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'E', 2, 'measure', elapsed_ms, rows_updated, 'HNSW+batched+gated(allchange)'
FROM _bench_batched_update_gated(0.00033);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'E', 3, 'measure', elapsed_ms, rows_updated, 'HNSW+batched+gated(allchange)'
FROM _bench_batched_update_gated(0.00034);

-- Quick look
SELECT condition, replicate, elapsed_ms, rows_updated, notes
FROM _bench_results
WHERE condition IN ('B','E')
ORDER BY condition, replicate;
