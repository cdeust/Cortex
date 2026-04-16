-- Phase 3: recreate HNSW and run condition A (3 replicates).

SET client_min_messages = WARNING;
\pset format unaligned

-- Rebuild HNSW index.
CREATE INDEX _bench_memories_hnsw_emb_idx
    ON _bench_memories_hnsw USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

SELECT 'hnsw_rebuilt' AS flag,
       pg_size_pretty(pg_relation_size('_bench_memories_hnsw_emb_idx')) AS idx_size;

-- ── Condition A: HNSW present, per-row UPDATE (single implicit txn) ──
SELECT _bench_reset_heat();
SELECT 'warmup_a' AS label, * FROM _bench_per_row_update(0.00061);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'A', 1, 'measure', elapsed_ms, rows_updated, 'HNSW+per-row'
FROM _bench_per_row_update(0.00062);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'A', 2, 'measure', elapsed_ms, rows_updated, 'HNSW+per-row'
FROM _bench_per_row_update(0.00063);

SELECT _bench_reset_heat();
INSERT INTO _bench_results (condition, replicate, kind, elapsed_ms, rows_updated, notes)
SELECT 'A', 3, 'measure', elapsed_ms, rows_updated, 'HNSW+per-row'
FROM _bench_per_row_update(0.00064);

-- Final summary.
SELECT condition,
       count(*) AS n,
       round(avg(elapsed_ms)::numeric,1) AS mean_ms,
       round(stddev(elapsed_ms)::numeric,1) AS stddev_ms,
       round(min(elapsed_ms)::numeric,1) AS min_ms,
       round(max(elapsed_ms)::numeric,1) AS max_ms
FROM _bench_results
GROUP BY condition
ORDER BY condition;
