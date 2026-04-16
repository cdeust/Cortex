-- scripts/v3_12_2_entity_canonical_merge.sql
-- ============================================================================
-- Cortex v3.12.2 — Entity Case-Variant Dedup Migration
-- Source: Curie I4 completeness audit (2026-04-16)
-- Spec: mcp_server/shared/entity_canonical.py (canonicalize_entity_name policy)
--
-- Problem (pre-migration):
--   Entity extraction did not case-canonicalize names at insert time, so
--   `Output` and `OUTPUT` and `output` all created separate rows.
--   Curie audit found 111 duplicate groups across 196 entity rows.
--
-- What this script does:
--   1. Identify duplicate groups: entities sharing LOWER(name).
--   2. For each group, pick the lowest-id row as survivor.
--   3. Reassign every memory_entities row pointing to non-survivor
--      to the survivor (ON CONFLICT deduplicates).
--   4. Reassign every relationships row (source + target) similarly.
--   5. Delete the non-survivor entity rows.
--   6. Update the survivor's name to the canonical form per policy
--      (name.title() when all-caps and length ≥ 4; else preserve).
--
-- Safety:
--   - Wrapped in a single BEGIN/COMMIT so partial failure rolls back.
--   - ON CONFLICT DO NOTHING guards the composite PK constraints.
--   - Pre-verification count + post-verification zero-duplicates assertion.
--   - Idempotent: re-running after success is a no-op.
--
-- Runbook:
--   1. pg_dump -Fc -t memory_entities -t entities -t relationships -d cortex \
--      > /var/backups/v3_12_2_entity_merge_pre_$(date +%Y%m%d_%H%M).dump
--   2. Run: psql "$DATABASE_URL" -f scripts/v3_12_2_entity_canonical_merge.sql
--   3. Verify: post-SELECT reports 0 duplicate groups.
--   4. Application: restart Cortex MCP (picks up new canonicalization in
--      pg_store_entities.insert_entity).
-- ============================================================================

BEGIN;
SET LOCAL statement_timeout = '600s';
SET LOCAL lock_timeout = '5s';

-- ----------------------------------------------------------------------------
-- 1. Baseline report
-- ----------------------------------------------------------------------------
SELECT 'pre_migration_duplicate_groups' AS metric, COUNT(*) AS value
  FROM (
    SELECT LOWER(name) AS canon, COUNT(*) AS c
      FROM entities
     GROUP BY LOWER(name)
    HAVING COUNT(*) > 1
  ) dup;

SELECT 'pre_migration_duplicate_row_count' AS metric, COUNT(*) AS value
  FROM entities e
  JOIN (
    SELECT LOWER(name) AS canon
      FROM entities
     GROUP BY LOWER(name)
    HAVING COUNT(*) > 1
  ) dup ON dup.canon = LOWER(e.name);

-- ----------------------------------------------------------------------------
-- 2. Build the merge plan as a temp table
--    For each duplicate group, survivor = MIN(id); non-survivors reassigned.
-- ----------------------------------------------------------------------------
CREATE TEMP TABLE _entity_merge_plan AS
SELECT
    e.id AS non_survivor_id,
    survivors.survivor_id,
    LOWER(e.name) AS canon
  FROM entities e
  JOIN (
    SELECT LOWER(name) AS canon, MIN(id) AS survivor_id, COUNT(*) AS n
      FROM entities
     GROUP BY LOWER(name)
    HAVING COUNT(*) > 1
  ) survivors ON survivors.canon = LOWER(e.name)
 WHERE e.id <> survivors.survivor_id;

SELECT 'merge_plan_size' AS metric, COUNT(*) AS value FROM _entity_merge_plan;

-- ----------------------------------------------------------------------------
-- 3. Reassign memory_entities rows (composite PK on memory_id + entity_id)
--    Strategy: insert new rows with survivor id, then delete the old rows.
--    ON CONFLICT dedupes the case where both variants linked to the same memory.
-- ----------------------------------------------------------------------------
INSERT INTO memory_entities (memory_id, entity_id)
SELECT me.memory_id, p.survivor_id
  FROM memory_entities me
  JOIN _entity_merge_plan p ON p.non_survivor_id = me.entity_id
ON CONFLICT DO NOTHING;

WITH deleted AS (
    DELETE FROM memory_entities
     WHERE entity_id IN (SELECT non_survivor_id FROM _entity_merge_plan)
     RETURNING 1
)
SELECT 'memory_entities_rows_deleted' AS metric, COUNT(*) AS value FROM deleted;

-- ----------------------------------------------------------------------------
-- 4. Reassign relationships rows
--    Composite PK likely on (source_entity_id, target_entity_id, relationship_type).
--    Same insert-then-delete pattern with conflict handling.
--    Also need to handle self-loops that may arise if both endpoints get the
--    same survivor id — delete those explicitly.
-- ----------------------------------------------------------------------------
INSERT INTO relationships (source_entity_id, target_entity_id, relationship_type, weight)
SELECT
    COALESCE(ps.survivor_id, r.source_entity_id),
    COALESCE(pt.survivor_id, r.target_entity_id),
    r.relationship_type,
    r.weight
  FROM relationships r
  LEFT JOIN _entity_merge_plan ps ON ps.non_survivor_id = r.source_entity_id
  LEFT JOIN _entity_merge_plan pt ON pt.non_survivor_id = r.target_entity_id
 WHERE ps.non_survivor_id IS NOT NULL OR pt.non_survivor_id IS NOT NULL
ON CONFLICT DO NOTHING;

WITH deleted AS (
    DELETE FROM relationships
     WHERE source_entity_id IN (SELECT non_survivor_id FROM _entity_merge_plan)
        OR target_entity_id IN (SELECT non_survivor_id FROM _entity_merge_plan)
     RETURNING 1
)
SELECT 'relationships_rows_deleted' AS metric, COUNT(*) AS value FROM deleted;

-- Delete any self-loops that survived the merge (same id on both sides).
WITH deleted AS (
    DELETE FROM relationships
     WHERE source_entity_id = target_entity_id
     RETURNING 1
)
SELECT 'self_loops_deleted' AS metric, COUNT(*) AS value FROM deleted;

-- ----------------------------------------------------------------------------
-- 5. Delete the non-survivor entity rows
-- ----------------------------------------------------------------------------
WITH deleted AS (
    DELETE FROM entities
     WHERE id IN (SELECT non_survivor_id FROM _entity_merge_plan)
     RETURNING 1
)
SELECT 'non_survivor_entities_deleted' AS metric, COUNT(*) AS value FROM deleted;

-- ----------------------------------------------------------------------------
-- 6. Canonicalize the survivor entity names
--    Policy: name.title() if name is ALL-CAPS AND length >= 4; else preserve.
--    Implemented in SQL as: WHERE name = UPPER(name) AND length(name) >= 4
--    AND regexp_match for at least one alpha character.
-- ----------------------------------------------------------------------------
WITH updated AS (
    UPDATE entities e
       SET name = initcap(e.name)
     WHERE e.name = UPPER(e.name)
       AND e.name ~ '[A-Z]'
       AND length(e.name) >= 4
       AND e.name <> initcap(e.name)
     RETURNING e.id
)
SELECT 'canonicalized_names_count' AS metric, COUNT(*) AS value FROM updated;

-- Note: PostgreSQL's initcap() handles underscores by capitalizing after them,
-- matching Python's str.title() behaviour on `HTTP_2` → `Http_2`.

-- ----------------------------------------------------------------------------
-- 7. Post-migration verification — must return 0
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    remaining_dupes INTEGER;
BEGIN
    SELECT COUNT(*) INTO remaining_dupes
      FROM (
        SELECT LOWER(name)
          FROM entities
         GROUP BY LOWER(name)
        HAVING COUNT(*) > 1
      ) d;
    IF remaining_dupes > 0 THEN
        RAISE EXCEPTION 'Migration incomplete: % duplicate groups remain', remaining_dupes;
    END IF;
    RAISE NOTICE 'post_migration: 0 duplicate groups (verified)';
END $$;

DROP TABLE _entity_merge_plan;

COMMIT;
