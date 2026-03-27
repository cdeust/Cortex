"""PostgreSQL schema: DDL, extensions, stored procedures, migrations.

Requires PostgreSQL 15+ with pgvector and pg_trgm extensions.
All retrieval logic lives in PL/pgSQL stored procedures.

Pure DDL — no connection management.
"""

from __future__ import annotations

# ── Extensions ────────────────────────────────────────────────────────────

EXTENSIONS_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""

# ── Core Tables ───────────────────────────────────────────────────────────

MEMORIES_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    id              SERIAL PRIMARY KEY,
    content         TEXT NOT NULL,
    embedding       vector(384),
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    tags            JSONB DEFAULT '[]'::jsonb,
    source          TEXT DEFAULT '',
    domain          TEXT DEFAULT '',
    directory_context TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heat            REAL DEFAULT 1.0,
    surprise_score  REAL DEFAULT 0.0,
    importance      REAL DEFAULT 0.5,
    emotional_valence REAL DEFAULT 0.0,
    confidence      REAL DEFAULT 1.0,
    access_count    INTEGER DEFAULT 0,
    useful_count    INTEGER DEFAULT 0,
    plasticity      REAL DEFAULT 1.0,
    stability       REAL DEFAULT 0.0,
    reconsolidation_count INTEGER DEFAULT 0,
    last_reconsolidated TIMESTAMPTZ,
    store_type      TEXT DEFAULT 'episodic',
    compressed      BOOLEAN DEFAULT FALSE,
    compression_level INTEGER DEFAULT 0,
    original_content TEXT,
    is_protected    BOOLEAN DEFAULT FALSE,
    is_stale        BOOLEAN DEFAULT FALSE,
    slot_index      INTEGER,
    excitability    REAL DEFAULT 1.0,
    consolidation_stage TEXT DEFAULT 'labile',
    hours_in_stage  REAL DEFAULT 0.0,
    replay_count    INTEGER DEFAULT 0,
    theta_phase_at_encoding REAL DEFAULT 0.0,
    encoding_strength REAL DEFAULT 1.0,
    separation_index REAL DEFAULT 0.0,
    interference_score REAL DEFAULT 0.0,
    schema_match_score REAL DEFAULT 0.0,
    schema_id       TEXT,
    hippocampal_dependency REAL DEFAULT 1.0,
    is_benchmark BOOLEAN DEFAULT FALSE,
    agent_context TEXT DEFAULT ''
);
"""

ENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS entities (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    domain          TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heat            REAL DEFAULT 1.0,
    archived        BOOLEAN DEFAULT FALSE
);
"""

RELATIONSHIPS_DDL = """
CREATE TABLE IF NOT EXISTS relationships (
    id                  SERIAL PRIMARY KEY,
    source_entity_id    INTEGER NOT NULL REFERENCES entities(id),
    target_entity_id    INTEGER NOT NULL REFERENCES entities(id),
    relationship_type   TEXT NOT NULL,
    weight              REAL DEFAULT 1.0,
    is_causal           BOOLEAN DEFAULT FALSE,
    confidence          REAL DEFAULT 1.0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_reinforced     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    release_probability REAL DEFAULT 0.5,
    facilitation        REAL DEFAULT 0.0,
    depression          REAL DEFAULT 0.0
);
"""

SUPPORT_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS prospective_memories (
    id                  SERIAL PRIMARY KEY,
    content             TEXT NOT NULL,
    trigger_condition   TEXT NOT NULL,
    trigger_type        TEXT NOT NULL,
    target_directory    TEXT,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_at        TIMESTAMPTZ,
    triggered_count     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id                  SERIAL PRIMARY KEY,
    session_id          TEXT DEFAULT 'default',
    directory_context   TEXT DEFAULT '',
    current_task        TEXT DEFAULT '',
    files_being_edited  JSONB DEFAULT '[]'::jsonb,
    key_decisions       JSONB DEFAULT '[]'::jsonb,
    open_questions      JSONB DEFAULT '[]'::jsonb,
    next_steps          JSONB DEFAULT '[]'::jsonb,
    active_errors       JSONB DEFAULT '[]'::jsonb,
    custom_context      TEXT DEFAULT '',
    epoch               INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active           BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS memory_archives (
    id                  SERIAL PRIMARY KEY,
    original_memory_id  INTEGER NOT NULL,
    content             TEXT NOT NULL,
    embedding           vector(384),
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mismatch_score      REAL DEFAULT 0.0,
    archive_reason      TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS consolidation_log (
    id                  SERIAL PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    memories_added      INTEGER DEFAULT 0,
    memories_updated    INTEGER DEFAULT 0,
    memories_archived   INTEGER DEFAULT 0,
    duration_ms         INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS engram_slots (
    slot_index          INTEGER PRIMARY KEY,
    excitability        REAL DEFAULT 0.5,
    last_activated      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS memory_rules (
    id                  SERIAL PRIMARY KEY,
    rule_type           TEXT NOT NULL DEFAULT 'soft',
    scope               TEXT NOT NULL DEFAULT 'global',
    scope_value         TEXT,
    condition           TEXT NOT NULL,
    action              TEXT NOT NULL,
    priority            INTEGER DEFAULT 0,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS schemas (
    id                      SERIAL PRIMARY KEY,
    schema_id               TEXT UNIQUE NOT NULL,
    domain                  TEXT DEFAULT '',
    label                   TEXT DEFAULT '',
    entity_signature        JSONB DEFAULT '{}'::jsonb,
    relationship_types      JSONB DEFAULT '[]'::jsonb,
    tag_signature           JSONB DEFAULT '{}'::jsonb,
    consistency_threshold   REAL DEFAULT 0.7,
    formation_count         INTEGER DEFAULT 0,
    assimilation_count      INTEGER DEFAULT 0,
    violation_count         INTEGER DEFAULT 0,
    last_updated            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS oscillatory_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    state_json  TEXT NOT NULL DEFAULT '{}'
);
"""

# ── Indexes ───────────────────────────────────────────────────────────────

INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_memories_content_tsv
    ON memories USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
    ON memories USING gin (content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_heat
    ON memories (heat);
CREATE INDEX IF NOT EXISTS idx_memories_domain
    ON memories (domain);
CREATE INDEX IF NOT EXISTS idx_memories_store_type
    ON memories (store_type);
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at);
CREATE INDEX IF NOT EXISTS idx_memories_stage
    ON memories (consolidation_stage);
CREATE INDEX IF NOT EXISTS idx_entities_name
    ON entities (name);
CREATE INDEX IF NOT EXISTS idx_entities_heat
    ON entities (heat);
CREATE INDEX IF NOT EXISTS idx_prospective_active
    ON prospective_memories (is_active);
CREATE INDEX IF NOT EXISTS idx_schemas_domain
    ON schemas (domain);
CREATE INDEX IF NOT EXISTS idx_rel_pair_type
    ON relationships (source_entity_id, target_entity_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_memories_agent_context
    ON memories (agent_context);
"""

# ── PL/pgSQL: recall_memories ─────────────────────────────────────────────

RECALL_MEMORIES_FN = """
CREATE OR REPLACE FUNCTION recall_memories(
    p_query_text    TEXT,
    p_query_emb     vector(384),
    p_intent        TEXT DEFAULT 'general',
    p_domain        TEXT DEFAULT NULL,
    p_directory     TEXT DEFAULT NULL,
    p_agent_topic   TEXT DEFAULT NULL,
    p_min_heat      REAL DEFAULT 0.05,
    p_max_results   INT DEFAULT 10,
    p_wrrf_k        INT DEFAULT 60,
    p_w_vector      REAL DEFAULT 1.0,
    p_w_fts         REAL DEFAULT 0.5,
    p_w_bm25        REAL DEFAULT 0.4,
    p_w_heat        REAL DEFAULT 0.3,
    p_w_ngram       REAL DEFAULT 0.3,
    p_w_recency     REAL DEFAULT 0.0
) RETURNS TABLE (
    memory_id       INT,
    content         TEXT,
    score           REAL,
    heat            REAL,
    domain          TEXT,
    created_at      TIMESTAMPTZ,
    store_type      TEXT,
    tags            JSONB,
    importance      REAL,
    surprise_score  REAL
) AS $$
DECLARE
    v_pool INT := p_max_results * 10;
    v_tsq  tsquery := plainto_tsquery('english', p_query_text);
BEGIN
    RETURN QUERY
    WITH
    -- Signal 1: Vector cosine similarity (pgvector HNSW)
    vec AS (
        SELECT m.id,
               ROW_NUMBER() OVER (ORDER BY m.embedding <=> p_query_emb) AS rank
        FROM memories m
        WHERE m.heat >= p_min_heat
          AND NOT m.is_stale
          AND m.embedding IS NOT NULL
          AND (p_domain IS NULL OR m.domain = p_domain)
          AND (p_directory IS NULL OR m.directory_context = p_directory)
        ORDER BY m.embedding <=> p_query_emb
        LIMIT v_pool
    ),
    -- Signal 2: Full-text search (tsvector + ts_rank_cd)
    fts AS (
        SELECT m.id,
               ROW_NUMBER() OVER (
                   ORDER BY ts_rank_cd(m.content_tsv, v_tsq) DESC
               ) AS rank
        FROM memories m
        WHERE m.content_tsv @@ v_tsq
          AND m.heat >= p_min_heat
          AND NOT m.is_stale
          AND (p_domain IS NULL OR m.domain = p_domain)
          AND (p_directory IS NULL OR m.directory_context = p_directory)
        ORDER BY ts_rank_cd(m.content_tsv, v_tsq) DESC
        LIMIT v_pool
    ),
    -- Signal 3: Trigram similarity (pg_trgm)
    ngram AS (
        SELECT m.id,
               ROW_NUMBER() OVER (
                   ORDER BY similarity(m.content, p_query_text) DESC
               ) AS rank
        FROM memories m
        WHERE m.heat >= p_min_heat
          AND NOT m.is_stale
          AND (p_domain IS NULL OR m.domain = p_domain)
          AND (p_directory IS NULL OR m.directory_context = p_directory)
          AND similarity(m.content, p_query_text) > 0.1
        ORDER BY similarity(m.content, p_query_text) DESC
        LIMIT v_pool
    ),
    -- Signal 4: Heat (thermodynamic relevance)
    hot AS (
        SELECT m.id,
               ROW_NUMBER() OVER (ORDER BY m.heat DESC) AS rank
        FROM memories m
        WHERE m.heat >= p_min_heat
          AND NOT m.is_stale
          AND (p_domain IS NULL OR m.domain = p_domain)
          AND (p_directory IS NULL OR m.directory_context = p_directory)
        ORDER BY m.heat DESC
        LIMIT v_pool
    ),
    -- Signal 5: Recency (newest first)
    recency AS (
        SELECT m.id,
               ROW_NUMBER() OVER (ORDER BY m.created_at DESC) AS rank
        FROM memories m
        WHERE m.heat >= p_min_heat
          AND NOT m.is_stale
          AND (p_domain IS NULL OR m.domain = p_domain)
          AND (p_directory IS NULL OR m.directory_context = p_directory)
        ORDER BY m.created_at DESC
        LIMIT v_pool
    ),
    -- WRRF Fusion: weight / (k + rank) for each signal
    fused AS (
        SELECT id, SUM(contribution) AS fused_score
        FROM (
            SELECT id, p_w_vector / (p_wrrf_k + rank) AS contribution FROM vec
            UNION ALL
            SELECT id, p_w_fts / (p_wrrf_k + rank) FROM fts
            UNION ALL
            SELECT id, p_w_ngram / (p_wrrf_k + rank) FROM ngram
            UNION ALL
            SELECT id, p_w_heat / (p_wrrf_k + rank) FROM hot
            UNION ALL
            SELECT id, p_w_recency / (p_wrrf_k + rank) FROM recency
            WHERE p_w_recency > 0
        ) signals
        GROUP BY id
    ),
    -- Signal 6: Agent topic boost (soft — boosts matching memories, never excludes)
    agent_boosted AS (
        SELECT f.id,
               CASE WHEN p_agent_topic IS NOT NULL
                         AND m.agent_context = p_agent_topic
                    THEN f.fused_score + 0.3 * (p_w_vector / p_wrrf_k)
                    ELSE f.fused_score
               END AS boosted_score
        FROM fused f
        JOIN memories m ON m.id = f.id
    )
    SELECT ab.id, m.content, ab.boosted_score::REAL, m.heat,
           m.domain, m.created_at, m.store_type,
           m.tags, m.importance, m.surprise_score
    FROM agent_boosted ab
    JOIN memories m ON m.id = ab.id
    ORDER BY ab.boosted_score DESC
    LIMIT p_max_results * 3;
END;
$$ LANGUAGE plpgsql STABLE;
"""

# ── PL/pgSQL: decay_memories ─────────────────────────────────────────────

DECAY_MEMORIES_FN = """
CREATE OR REPLACE FUNCTION decay_memories(
    p_factor    REAL DEFAULT 0.95,
    p_threshold REAL DEFAULT 0.05
) RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE memories
    SET heat = heat * p_factor
    WHERE NOT is_protected AND NOT is_stale AND heat >= p_threshold;

    GET DIAGNOSTICS v_count = ROW_COUNT;

    UPDATE memories
    SET is_stale = TRUE
    WHERE heat < p_threshold AND NOT is_protected AND NOT is_stale;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;
"""

# ── PL/pgSQL: spread_activation ──────────────────────────────────────────

SPREAD_ACTIVATION_FN = """
CREATE OR REPLACE FUNCTION spread_activation(
    p_seed_entity_ids INT[],
    p_decay           REAL DEFAULT 0.65,
    p_threshold       REAL DEFAULT 0.1,
    p_max_depth       INT DEFAULT 3
) RETURNS TABLE (
    entity_id   INT,
    activation  REAL
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE spread AS (
        -- Seed nodes
        SELECT unnest(p_seed_entity_ids) AS eid, 1.0::REAL AS act, 0 AS depth
        UNION ALL
        -- Propagate through relationships
        SELECT
            CASE
                WHEN r.source_entity_id = s.eid THEN r.target_entity_id
                ELSE r.source_entity_id
            END AS eid,
            (s.act * p_decay * r.weight)::REAL AS act,
            s.depth + 1 AS depth
        FROM spread s
        JOIN relationships r
            ON r.source_entity_id = s.eid OR r.target_entity_id = s.eid
        WHERE s.depth < p_max_depth
          AND s.act * p_decay * r.weight >= p_threshold
    )
    SELECT s.eid, MAX(s.act)::REAL
    FROM spread s
    JOIN entities e ON e.id = s.eid
    WHERE e.heat >= 0.05 AND NOT e.archived
    GROUP BY s.eid
    ORDER BY MAX(s.act) DESC;
END;
$$ LANGUAGE plpgsql STABLE;
"""

# ── PL/pgSQL: spread_activation_memories ────────────────────────────────
# Full pipeline: query terms → entity resolution → propagation → memory IDs.
# Replaces 4 Python-side round trips with 1 server-side call.

SPREAD_ACTIVATION_MEMORIES_FN = """
CREATE OR REPLACE FUNCTION spread_activation_memories(
    p_query_terms   TEXT[],
    p_decay         REAL DEFAULT 0.65,
    p_threshold     REAL DEFAULT 0.1,
    p_max_depth     INT DEFAULT 3,
    p_max_results   INT DEFAULT 50,
    p_min_heat      REAL DEFAULT 0.05
) RETURNS TABLE (
    memory_id   INT,
    activation  REAL
) AS $$
BEGIN
    RETURN QUERY
    WITH
    -- Step 1: Resolve query terms to entity IDs (case-insensitive)
    seed_entities AS (
        SELECT DISTINCT e.id AS eid
        FROM entities e, unnest(p_query_terms) AS t(term)
        WHERE LOWER(e.name) = LOWER(t.term)
          AND e.heat >= p_min_heat
          AND NOT e.archived
    ),
    seed_ids AS (
        SELECT ARRAY_AGG(eid) AS ids FROM seed_entities
    ),
    -- Step 2: Spread activation via recursive CTE
    spread AS (
        SELECT se.eid, 1.0::REAL AS act, 0 AS depth
        FROM seed_entities se
        UNION ALL
        SELECT
            CASE
                WHEN r.source_entity_id = s.eid THEN r.target_entity_id
                ELSE r.source_entity_id
            END AS eid,
            (s.act * p_decay * r.weight * r.confidence)::REAL AS act,
            s.depth + 1 AS depth
        FROM spread s
        JOIN relationships r
            ON r.source_entity_id = s.eid OR r.target_entity_id = s.eid
        WHERE s.depth < p_max_depth
          AND s.act * p_decay * r.weight * r.confidence >= p_threshold
    ),
    -- Aggregate activations per entity (max, not sum — prevents over-boost)
    entity_acts AS (
        SELECT s.eid, MAX(s.act)::REAL AS act
        FROM spread s
        JOIN entities e ON e.id = s.eid
        WHERE e.heat >= p_min_heat AND NOT e.archived
        GROUP BY s.eid
    ),
    -- Step 3: Map entity activations to memories via FTS + ILIKE
    entity_memories AS (
        SELECT DISTINCT m.id AS mid, ea.act
        FROM entity_acts ea
        JOIN entities e ON e.id = ea.eid
        JOIN memories m
            ON m.content_tsv @@ phraseto_tsquery('english', e.name)
        WHERE m.heat >= p_min_heat AND NOT m.is_stale
    )
    -- Return max activation per memory (entity with strongest path wins)
    SELECT em.mid, MAX(em.act)::REAL
    FROM entity_memories em
    GROUP BY em.mid
    ORDER BY MAX(em.act) DESC
    LIMIT p_max_results;
END;
$$ LANGUAGE plpgsql STABLE;
"""

# ── PL/pgSQL: get_hot_embeddings ────────────────────────────────────────
# Efficient batch fetch of memory IDs + embeddings for Hopfield/HDC.
# Avoids loading full memory rows — only id + embedding bytes.

GET_HOT_EMBEDDINGS_FN = """
CREATE OR REPLACE FUNCTION get_hot_embeddings(
    p_min_heat    REAL DEFAULT 0.05,
    p_domain      TEXT DEFAULT NULL,
    p_limit       INT DEFAULT 500
) RETURNS TABLE (
    memory_id   INT,
    embedding   vector(384),
    heat        REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT m.id, m.embedding, m.heat
    FROM memories m
    WHERE m.heat >= p_min_heat
      AND NOT m.is_stale
      AND m.embedding IS NOT NULL
      AND (p_domain IS NULL OR m.domain = p_domain)
    ORDER BY m.heat DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;
"""

# ── PL/pgSQL: get_temporal_co_access ────────────────────────────────────
# Returns memory pairs accessed within a time window (for SR graph building).
# Computes proximity weight: 1.0 - (gap_seconds / window_seconds).

GET_TEMPORAL_CO_ACCESS_FN = """
CREATE OR REPLACE FUNCTION get_temporal_co_access(
    p_window_hours  REAL DEFAULT 2.0,
    p_min_access    INT DEFAULT 1,
    p_limit         INT DEFAULT 100
) RETURNS TABLE (
    mem_a       INT,
    mem_b       INT,
    proximity   REAL
) AS $$
DECLARE
    v_window INTERVAL := (p_window_hours || ' hours')::INTERVAL;
BEGIN
    RETURN QUERY
    WITH recent AS (
        SELECT id, last_accessed
        FROM memories
        WHERE access_count >= p_min_access
          AND NOT is_stale
          AND last_accessed IS NOT NULL
        ORDER BY last_accessed DESC
        LIMIT p_limit
    )
    SELECT
        a.id AS mem_a,
        b.id AS mem_b,
        (1.0 - EXTRACT(EPOCH FROM (b.last_accessed - a.last_accessed))
             / EXTRACT(EPOCH FROM v_window))::REAL AS proximity
    FROM recent a
    JOIN recent b
        ON b.id > a.id
        AND b.last_accessed BETWEEN a.last_accessed AND a.last_accessed + v_window
    ORDER BY proximity DESC;
END;
$$ LANGUAGE plpgsql STABLE;
"""


# ── Migrations ───────────────────────────────────────────────────────────

MIGRATIONS_DDL = """
-- Add is_benchmark column (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'is_benchmark'
    ) THEN
        ALTER TABLE memories ADD COLUMN is_benchmark BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- Backfill: mark benchmark and test-artifact memories
UPDATE memories SET is_benchmark = TRUE
WHERE is_benchmark = FALSE
  AND (
    domain IN ('beam', 'locomo', 'longmemeval', 'memoryagentbench',
               'evermembench', 'episodic', 'unknown', 'alpha', 'beta')
    OR source = 'cls-consolidation'
    OR content LIKE 'Recurring pattern across %% observations:%%'
    OR content LIKE 'Session test-%%'
    OR content LIKE 'Shape test content%%'
    OR content LIKE 'Force stored memory%%'
    OR content LIKE 'Response shape test%%'
    OR content = 'protected memory content'
    OR content = 'Something mildly interesting happened today'
    OR content = 'test memory for consolidation'
  );

-- Partial index for fast non-benchmark queries
CREATE INDEX IF NOT EXISTS idx_memories_not_benchmark
    ON memories (heat DESC) WHERE NOT is_benchmark;

-- Migration: add agent_context column for agent-scoped memory
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'agent_context'
    ) THEN
        ALTER TABLE memories ADD COLUMN agent_context TEXT DEFAULT '';
    END IF;
END $$;
"""

# ── Schema initialization ────────────────────────────────────────────────


def get_all_ddl() -> list[str]:
    """Return all DDL statements in execution order."""
    return [
        EXTENSIONS_DDL,
        MEMORIES_DDL,
        ENTITIES_DDL,
        RELATIONSHIPS_DDL,
        SUPPORT_TABLES_DDL,
        INDEXES_DDL,
        MIGRATIONS_DDL,
        RECALL_MEMORIES_FN,
        DECAY_MEMORIES_FN,
        SPREAD_ACTIVATION_FN,
        SPREAD_ACTIVATION_MEMORIES_FN,
        GET_HOT_EMBEDDINGS_FN,
        GET_TEMPORAL_CO_ACCESS_FN,
    ]
