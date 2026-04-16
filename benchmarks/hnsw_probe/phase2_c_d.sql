-- Phase 2 (HNSW absent): conditions C and D — controls that isolate HNSW cost.

SET client_min_messages = WARNING;
\pset format unaligned

-- Drop the HNSW index.
DROP INDEX IF EXISTS _bench_memories_hnsw_emb_idx;

-- Confirm no HNSW index present.
SELECT 'hnsw_present' AS flag, COUNT(*) FROM pg_indexes
WHERE tablename = '_bench_memories_hnsw' AND indexname LIKE '%hnsw%';

-- VACUUM to clean up any dead tuples from the previous phase
-- (HNSW-present conditions left bloat because batched UPDATE creates new tuple versions).
VACUUM (ANALYZE) _bench_memories_hnsw;

-- ── Condition C: no HNSW, per-row UPDATE ──
SELECT _bench_reset_heat();
SELECT 'warmup_c' AS label, * FROM _bench_per_row_update(0.00041);

-- Replicates 1..3
SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'C', 1, 'measure', elapsed_ms, rows_updated, 'noHNSW+per-row'
FROM _bench_per_row_update(0.00042);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'C', 2, 'measure', elapsed_ms, rows_updated, 'noHNSW+per-row'
FROM _bench_per_row_update(0.00043);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'C', 3, 'measure', elapsed_ms, rows_updated, 'noHNSW+per-row'
FROM _bench_per_row_update(0.00044);

-- ── Condition D: no HNSW, batched UPDATE ──
SELECT _bench_reset_heat();
SELECT 'warmup_d' AS label, * FROM _bench_batched_update(0.00051);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'D', 1, 'measure', elapsed_ms, rows_updated, 'noHNSW+batched'
FROM _bench_batched_update(0.00052);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'D', 2, 'measure', elapsed_ms, rows_updated, 'noHNSW+batched'
FROM _bench_batched_update(0.00053);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'D', 3, 'measure', elapsed_ms, rows_updated, 'noHNSW+batched'
FROM _bench_batched_update(0.00054);

-- Quick look.
SELECT condition, replicate, round(elapsed_ms::numeric,1) AS ms, rows_updated, notes
FROM _bench_results
WHERE condition IN ('C','D')
ORDER BY condition, replicate;
