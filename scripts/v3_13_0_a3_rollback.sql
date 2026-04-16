-- scripts/v3_13_0_a3_rollback.sql
-- ============================================================================
-- Cortex v3.13.0 — Phase 3 A3 rollback
--
-- Reverses v3_13_0_a3_migration.sql:
--   1. Un-partition memories (re-merge partitions into a single table).
--   2. Rename heat_base → heat.
--   3. Drop heat_base_set_at, no_decay columns.
--   4. Drop homeostatic_state table.
--   5. Drop ensure_memory_partition_for() helper.
--
-- Runbook:
--   1. Flip CORTEX_MEMORY_A3_LAZY_HEAT=false in every running process.
--   2. pg_dump current state (for diagnostic purposes).
--   3. psql "$DATABASE_URL" -f scripts/v3_13_0_a3_rollback.sql
--   4. Verify: SELECT column_name FROM information_schema.columns
--              WHERE table_name='memories' AND column_name='heat'; → 1 row
--   5. Restart Cortex; decay + homeostatic cycles resume their eager form.
--
-- Note: any writes to homeostatic_state.factor since migration are lost
-- by design. The factor was never a source of truth — heat_base was.
-- ============================================================================

BEGIN;
SET LOCAL statement_timeout = '30min';
SET LOCAL lock_timeout = '30s';

-- 1. Rebuild a non-partitioned memories table, copy all data, swap names.
DO $$
DECLARE
    is_partitioned BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM pg_partitioned_table p
                 JOIN pg_class c ON c.oid = p.partrelid
         WHERE c.relname = 'memories'
    ) INTO is_partitioned;
    IF NOT is_partitioned THEN
        RAISE NOTICE 'memories already non-partitioned — skipping repack';
        RETURN;
    END IF;

    ALTER TABLE memories RENAME TO memories_a3;
    EXECUTE 'CREATE TABLE memories (LIKE memories_a3 INCLUDING ALL)';
    INSERT INTO memories SELECT * FROM memories_a3;
    DROP TABLE memories_a3 CASCADE;
END $$;

-- 2. Rename heat_base → heat (if renamed).
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'memories' AND column_name = 'heat_base'
    ) THEN
        ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_heat_base_bounds;
        ALTER TABLE memories RENAME COLUMN heat_base TO heat;
        ALTER TABLE memories ALTER COLUMN heat SET DEFAULT 1.0;
    END IF;
END $$;

-- 3. Drop heat_base_set_at + no_decay columns.
ALTER TABLE memories
    DROP COLUMN IF EXISTS heat_base_set_at,
    DROP COLUMN IF EXISTS no_decay;

-- 4. Drop homeostatic_state table.
DROP TABLE IF EXISTS homeostatic_state;

-- 5. Drop partition-auto-creator helper.
DROP FUNCTION IF EXISTS ensure_memory_partition_for(DATE);

-- Post-verification.
SELECT 'a3_rollback_complete' AS marker,
       (SELECT COUNT(*) FROM memories) AS total_memories,
       (SELECT EXISTS(SELECT 1 FROM information_schema.columns
         WHERE table_name='memories' AND column_name='heat')) AS heat_restored,
       (SELECT NOT EXISTS(SELECT 1 FROM information_schema.tables
         WHERE table_name='homeostatic_state')) AS homeostatic_dropped;

COMMIT;
