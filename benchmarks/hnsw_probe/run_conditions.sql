-- HNSW UPDATE cost probe. Five conditions, three replicates each.
--
-- Conditions:
--   A) HNSW present,  per-row UPDATE (single txn)   — PL/pgSQL loop
--   B) HNSW present,  batched UPDATE                — UNNEST pattern (v3.11)
--   C) HNSW absent,   per-row UPDATE (single txn)   — control
--   D) HNSW absent,   batched UPDATE                — control
--   E) HNSW present,  batched UPDATE + IS DISTINCT FROM gating   — v3.12 candidate
--
-- Plus probe F) HNSW present, per-row UPDATE with per-row COMMIT
--             (matches production exactly)  — only measure once due to runtime.
--
-- Measurement: server-side clock_timestamp() deltas. No psycopg/round-trip noise.
-- This is strictly a LOWER bound on production cost (prod has network+python overhead).
-- If HNSW signal is strong here, it's strong in prod.
--
-- Gating: each replicate uses a unique delta so every UPDATE changes the heat value.
-- This ensures we never hit an IS DISTINCT FROM no-op by accident.

\timing off
SET client_min_messages = WARNING;

-- Results table
DROP TABLE IF EXISTS _bench_results;
CREATE TABLE _bench_results (
    condition   TEXT,
    replicate   INT,
    kind        TEXT,        -- 'warmup' or 'measure'
    elapsed_ms  REAL,
    rows_updated INT,
    notes       TEXT
);

-- ── Helper functions ────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION _bench_per_row_update(p_delta REAL)
RETURNS TABLE(elapsed_ms REAL, rows_updated INT) AS $$
DECLARE
    v_start TIMESTAMPTZ;
    v_id INT;
    v_rows INT := 0;
BEGIN
    v_start := clock_timestamp();
    FOR v_id IN SELECT id FROM _bench_memories_hnsw ORDER BY id LOOP
        UPDATE _bench_memories_hnsw
           SET heat = heat + p_delta
         WHERE id = v_id;
        v_rows := v_rows + 1;
    END LOOP;
    elapsed_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_start)) * 1000.0;
    rows_updated := v_rows;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _bench_batched_update(p_delta REAL)
RETURNS TABLE(elapsed_ms REAL, rows_updated INT) AS $$
DECLARE
    v_start TIMESTAMPTZ;
    v_rows INT;
BEGIN
    v_start := clock_timestamp();
    WITH new_heats AS (
        SELECT id, heat + p_delta AS new_heat
        FROM _bench_memories_hnsw
    )
    UPDATE _bench_memories_hnsw m
       SET heat = n.new_heat
      FROM new_heats n
     WHERE m.id = n.id;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    elapsed_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_start)) * 1000.0;
    rows_updated := v_rows;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _bench_batched_update_gated(p_delta REAL)
RETURNS TABLE(elapsed_ms REAL, rows_updated INT) AS $$
DECLARE
    v_start TIMESTAMPTZ;
    v_rows INT;
BEGIN
    v_start := clock_timestamp();
    WITH new_heats AS (
        SELECT id, heat + p_delta AS new_heat
        FROM _bench_memories_hnsw
    )
    UPDATE _bench_memories_hnsw m
       SET heat = n.new_heat
      FROM new_heats n
     WHERE m.id = n.id
       AND m.heat IS DISTINCT FROM n.new_heat;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    elapsed_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_start)) * 1000.0;
    rows_updated := v_rows;
    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- Per-row with per-row COMMIT (production semantics) — stored procedure.
CREATE OR REPLACE PROCEDURE _bench_per_row_update_commit(p_delta REAL,
                                                        OUT p_elapsed_ms REAL,
                                                        OUT p_rows_updated INT)
LANGUAGE plpgsql AS $$
DECLARE
    v_start TIMESTAMPTZ;
    v_id INT;
    v_rows INT := 0;
BEGIN
    v_start := clock_timestamp();
    FOR v_id IN SELECT id FROM _bench_memories_hnsw ORDER BY id LOOP
        UPDATE _bench_memories_hnsw
           SET heat = heat + p_delta
         WHERE id = v_id;
        v_rows := v_rows + 1;
        COMMIT;
    END LOOP;
    p_elapsed_ms := EXTRACT(EPOCH FROM (clock_timestamp() - v_start)) * 1000.0;
    p_rows_updated := v_rows;
END;
$$;

-- Helper to keep heat values bounded: normalize heat back into a tight band
-- (we don't want heat to drift across many replicates and saturate).
CREATE OR REPLACE FUNCTION _bench_reset_heat()
RETURNS VOID AS $$
BEGIN
    -- Restore heat to random uniform[0, 1] for each row using row-level random.
    UPDATE _bench_memories_hnsw SET heat = random()::real;
END;
$$ LANGUAGE plpgsql;

-- Helper to drop / recreate HNSW (used between conditions).
-- Drop: instant. Create: ~100s on 66K rows (measured in setup).
-- We'll cache this by running WITH-HNSW conditions consecutively, then WITHOUT.

SELECT 'Helpers installed' AS status;
