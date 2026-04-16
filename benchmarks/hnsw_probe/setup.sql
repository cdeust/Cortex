-- Setup bench table matching Cortex memories schema for HNSW probe.
-- Source: pg_schema.py lines 20-65 (MEMORIES_DDL) and lines 476-477 (HNSW index).
-- HNSW index: USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)

\timing on

DROP TABLE IF EXISTS _bench_memories_hnsw;

CREATE TABLE _bench_memories_hnsw (
    id              SERIAL PRIMARY KEY,
    heat            REAL DEFAULT 1.0,
    embedding       vector(384)
);

-- Disable autovacuum on this table to avoid contaminating measurements.
ALTER TABLE _bench_memories_hnsw SET (autovacuum_enabled = false);

-- Helper: generate an L2-normalized random 384-dim vector as text "[v1,v2,...]".
-- L2 normalization matches sentence-transformers all-MiniLM-L6-v2 output.
CREATE OR REPLACE FUNCTION _bench_random_unit_vec_384()
RETURNS vector(384) AS $$
DECLARE
    v_arr float8[];
    v_norm float8 := 0.0;
    v_i int;
    v_str text := '[';
BEGIN
    SELECT array_agg(random() * 2.0 - 1.0) INTO v_arr
    FROM generate_series(1, 384);
    FOR v_i IN 1..384 LOOP
        v_norm := v_norm + v_arr[v_i] * v_arr[v_i];
    END LOOP;
    v_norm := sqrt(v_norm);
    FOR v_i IN 1..384 LOOP
        IF v_i > 1 THEN v_str := v_str || ','; END IF;
        v_str := v_str || (v_arr[v_i] / v_norm)::text;
    END LOOP;
    v_str := v_str || ']';
    RETURN v_str::vector;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- Seed 66,064 rows.
INSERT INTO _bench_memories_hnsw (heat, embedding)
SELECT random()::real, _bench_random_unit_vec_384()
FROM generate_series(1, 66064);

SELECT COUNT(*) AS seeded_rows FROM _bench_memories_hnsw;

-- Build the HNSW index AFTER seeding (matches Cortex production init order).
-- Note: initial build cost is separate from per-UPDATE maintenance cost.
CREATE INDEX _bench_memories_hnsw_emb_idx
    ON _bench_memories_hnsw USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Verify.
SELECT pg_size_pretty(pg_relation_size('_bench_memories_hnsw')) AS table_size,
       pg_size_pretty(pg_relation_size('_bench_memories_hnsw_emb_idx')) AS hnsw_idx_size;
