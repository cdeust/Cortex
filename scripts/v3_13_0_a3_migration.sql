-- scripts/v3_13_0_a3_migration.sql
-- ============================================================================
-- Cortex v3.13.0 — Phase 3 A3 atomic migration (lazy heat)
--
-- Source: docs/program/phase-3-a3-migration-design.md §1 (schema migration).
-- Invariants: I1 (heat ∈ [0,1]), I2 (one canonical writer), I5 (stage decay
-- exponents in effective_heat), I10 (still applies at pool layer).
--
-- What this DDL does:
--   1. Rename memories.heat → memories.heat_base + add CHECK bounds.
--   2. Add memories.heat_base_set_at (provenance timestamp for the bump).
--   3. Add memories.no_decay (anchor + import-pin flag).
--   4. Create homeostatic_state table (one row per domain, scalar factor).
--   5. Monthly RANGE partition memories on created_at (Thompson D1).
--   6. Per-partition HNSW / GIN / B-tree indexes (pgvector #875 mitigation).
--   7. ensure_memory_partition_for() helper for auto-creation.
--
-- What this DDL does NOT do (that's steps 2-8 of the spec):
--   - Add effective_heat() function (step 2 lands that in pg_schema.py).
--   - Rewrite recall_memories() (step 6).
--   - Delete decay_memories() (step 7).
--   - Flip the A3_LAZY_HEAT flag (step 9).
--
-- Safety:
--   - Wrapped in a single BEGIN/COMMIT with 30-min statement_timeout.
--   - Every DDL is IF NOT EXISTS or DROP IF EXISTS (idempotent re-run).
--   - INSERT INTO copy of memories → partitioned memories; tested on
--     darval-scale 66K in ~4 minutes per spec §1.3.
--   - Companion rollback at scripts/v3_13_0_a3_rollback.sql.
--
-- Runbook:
--   1. pg_dump -Fc -t memories -t memory_entities -t relationships \
--        -d $DATABASE_URL > /var/backups/pre_a3_$(date +%Y%m%d_%H%M).dump
--   2. Stop consolidate + hooks: set CORTEX_PAUSED=1
--   3. psql "$DATABASE_URL" -f scripts/v3_13_0_a3_migration.sql
--   4. Verify: SELECT COUNT(*) FROM memories; — matches pre-migration count.
--   5. Verify: SELECT EXISTS(SELECT 1 FROM information_schema.columns
--                WHERE table_name='memories' AND column_name='heat_base');
--              → t
--   6. Run tests: pytest tests_py/invariants/test_I1_heat_bounds.py
--   7. Resume consolidate (CORTEX_PAUSED=0); flag still false.
-- ============================================================================

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '30s';

-- ----------------------------------------------------------------------------
-- 1.1 Rename heat → heat_base + add CHECK bounds (I1 preserved).
-- ----------------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'memories' AND column_name = 'heat_base'
    ) THEN
        ALTER TABLE memories RENAME COLUMN heat TO heat_base;
        ALTER TABLE memories ALTER COLUMN heat_base SET DEFAULT 1.0;
        ALTER TABLE memories ADD CONSTRAINT memories_heat_base_bounds
            CHECK (heat_base >= 0.0 AND heat_base <= 1.0);
    END IF;
END $$;

-- 1.2 Add heat_base_set_at + no_decay columns.
ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS heat_base_set_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS no_decay BOOLEAN NOT NULL DEFAULT FALSE;

-- Back-populate heat_base_set_at from last_accessed (Lamport §3: the last
-- known causal touch is our best proxy for when heat_base was last valid).
UPDATE memories
   SET heat_base_set_at = COALESCE(last_accessed, created_at, NOW())
 WHERE heat_base_set_at IS NULL;

ALTER TABLE memories ALTER COLUMN heat_base_set_at SET NOT NULL;
ALTER TABLE memories ALTER COLUMN heat_base_set_at SET DEFAULT NOW();

-- ----------------------------------------------------------------------------
-- 1.3 Homeostatic state (one row per domain, scalar factor).
-- Feynman: heat is a function, not a state — the cycle adjusts a scalar.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS homeostatic_state (
    domain     TEXT PRIMARY KEY,
    factor     REAL NOT NULL DEFAULT 1.0
               CHECK (factor > 0.0 AND factor < 10.0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default per-domain rows discovered from memories. Readers MUST
-- still COALESCE((SELECT factor FROM homeostatic_state WHERE domain=…), 1.0)
-- because new domains arriving between seed and first homeostatic run
-- would otherwise miss their row.
INSERT INTO homeostatic_state (domain, factor)
SELECT DISTINCT COALESCE(domain, ''), 1.0
  FROM memories
 WHERE domain IS NOT NULL
ON CONFLICT (domain) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 1.4 Monthly RANGE partition on memories.created_at (Thompson D1).
-- Strategy: rename memories → memories_pre_a3, create new partitioned
-- memories with IDENTICAL schema, INSERT INTO to copy data, drop old.
-- For stores < 1M rows this finishes in ≤5 min per spec §1.3.
-- ----------------------------------------------------------------------------
DO $$ DECLARE
    is_partitioned BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_partitioned_table p
                 JOIN pg_class c ON c.oid = p.partrelid
         WHERE c.relname = 'memories'
    ) INTO is_partitioned;
    IF is_partitioned THEN
        RAISE NOTICE 'memories is already partitioned — skipping partition setup';
        RETURN;
    END IF;

    -- Rename existing memories to memories_pre_a3.
    ALTER TABLE memories RENAME TO memories_pre_a3;

    -- New partitioned memories table, same schema, partition by created_at.
    EXECUTE 'CREATE TABLE memories (LIKE memories_pre_a3 INCLUDING ALL) '
            'PARTITION BY RANGE (created_at)';

    -- Pre-create 12 partitions from current month forward + 1 historical.
    FOR i IN 0..11 LOOP
        DECLARE
            start_d DATE := (date_trunc('month', NOW()) + (i || ' months')::interval)::DATE;
            end_d   DATE := (date_trunc('month', NOW()) + ((i+1) || ' months')::interval)::DATE;
            pname   TEXT := 'memories_' || to_char(start_d, 'YYYY_MM');
        BEGIN
            EXECUTE format(
              'CREATE TABLE IF NOT EXISTS %I PARTITION OF memories '
              'FOR VALUES FROM (%L) TO (%L)', pname, start_d, end_d);
        END;
    END LOOP;

    -- Historical catch-all for pre-current-month data. Keeps all darval-era
    -- memories queryable without rewriting them into monthly partitions.
    EXECUTE 'CREATE TABLE IF NOT EXISTS memories_historical '
            'PARTITION OF memories '
            'FOR VALUES FROM (MINVALUE) TO (%L)',
            array[date_trunc('month', NOW())::DATE]::TEXT[];

    -- Copy data from old table → partitioned memories.
    INSERT INTO memories SELECT * FROM memories_pre_a3;

    -- Drop the pre-A3 table now that data is migrated.
    DROP TABLE memories_pre_a3 CASCADE;
END $$;

-- ----------------------------------------------------------------------------
-- 1.5 Per-partition indexes. Smaller indexes = faster UPDATE maintenance.
-- pgvector #875 mitigation: HNSW re-insert cost scales with partition size,
-- not total store. B-tree(heat_base) preserves ORDER BY usability for
-- the recall hot CTE post-A3.
-- ----------------------------------------------------------------------------
DO $$ DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT n.nspname AS schemaname, c.relname AS tablename
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relkind = 'r'
           AND c.relname LIKE 'memories_%'
           AND n.nspname = 'public'
    LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I '
            'USING hnsw (embedding vector_cosine_ops) '
            'WITH (m = 16, ef_construction = 64)',
            'idx_' || r.tablename || '_embedding', r.schemaname, r.tablename);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I '
            'USING gin (content_tsv)',
            'idx_' || r.tablename || '_content_tsv', r.schemaname, r.tablename);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I '
            'USING gin (content gin_trgm_ops)',
            'idx_' || r.tablename || '_content_trgm', r.schemaname, r.tablename);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I (heat_base)',
            'idx_' || r.tablename || '_heat_base', r.schemaname, r.tablename);
    END LOOP;
END $$;

-- ----------------------------------------------------------------------------
-- 1.6 Auto-create next month's partition on demand. Called at start of
-- consolidate so no cron needed.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ensure_memory_partition_for(target DATE)
RETURNS VOID AS $$
DECLARE
    part_name TEXT := 'memories_' || to_char(target, 'YYYY_MM');
    start_d   DATE := date_trunc('month', target)::DATE;
    end_d     DATE := (date_trunc('month', target) + interval '1 month')::DATE;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relname = part_name AND n.nspname = 'public'
    ) THEN
        EXECUTE format(
            'CREATE TABLE %I PARTITION OF memories '
            'FOR VALUES FROM (%L) TO (%L)', part_name, start_d, end_d);
        -- Re-create the 4 indexes on the new partition.
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I '
            'USING hnsw (embedding vector_cosine_ops) '
            'WITH (m = 16, ef_construction = 64)',
            'idx_' || part_name || '_embedding', part_name);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I USING gin (content_tsv)',
            'idx_' || part_name || '_content_tsv', part_name);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I '
            'USING gin (content gin_trgm_ops)',
            'idx_' || part_name || '_content_trgm', part_name);
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I (heat_base)',
            'idx_' || part_name || '_heat_base', part_name);
    END IF;
END $$ LANGUAGE plpgsql;

-- ----------------------------------------------------------------------------
-- Post-verification: report final state.
-- ----------------------------------------------------------------------------
SELECT 'a3_migration_complete' AS marker,
       (SELECT COUNT(*) FROM memories)                         AS total_memories,
       (SELECT COUNT(*) FROM pg_class c
         JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname LIKE 'memories_%'
          AND c.relkind = 'r'
          AND n.nspname = 'public')                            AS partition_count,
       (SELECT COUNT(*) FROM homeostatic_state)                AS homeostatic_rows,
       (SELECT EXISTS(SELECT 1 FROM information_schema.columns
         WHERE table_name='memories' AND column_name='heat_base')) AS heat_base_present;

COMMIT;
