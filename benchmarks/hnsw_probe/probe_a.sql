-- Quick probe: one warmup + one measurement of condition A (HNSW + per-row UPDATE).
-- If this takes > 5 min we have our answer on direction and can adjust.

SET client_min_messages = WARNING;

-- Confirm HNSW index is present.
SELECT indexname FROM pg_indexes
WHERE tablename = '_bench_memories_hnsw' AND indexname LIKE '%hnsw%';

-- Reset heat to fresh random state.
SELECT _bench_reset_heat();

-- WARMUP
SELECT 'warmup_a' AS phase, * FROM _bench_per_row_update(0.00011);

-- Reset and measure
SELECT _bench_reset_heat();
SELECT 'measure_a_r1' AS phase, * FROM _bench_per_row_update(0.00012);
