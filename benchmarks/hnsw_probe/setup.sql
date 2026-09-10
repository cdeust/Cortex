-- source: ADR-0835



\timing on

DROP TABLE IF EXISTS _bench_memories_hnsw;

CREATE TABLE _bench_memories_hnsw (
    id              SERIAL PRIMARY KEY,
    heat            REAL DEFAULT 1.0,
    embedding       vector(384)
);

-- source: ADR-0835
ALTER TABLE _bench_memories_hnsw SET (autovacuum_enabled = false);

-- Generate an L2-normalized random 384-dimensional vector as text.
-- source: ADR-0835
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

-- Build the HNSW index after seeding.
-- source: ADR-0835
CREATE INDEX _bench_memories_hnsw_emb_idx
    ON _bench_memories_hnsw USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Verify.
SELECT pg_size_pretty(pg_relation_size('_bench_memories_hnsw')) AS table_size,
       pg_size_pretty(pg_relation_size('_bench_memories_hnsw_emb_idx')) AS hnsw_idx_size;
