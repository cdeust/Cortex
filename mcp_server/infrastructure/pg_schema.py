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
    heat_base       REAL NOT NULL DEFAULT 1.0
                    CHECK (heat_base >= 0.0 AND heat_base <= 1.0),
    heat_base_set_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    no_decay        BOOLEAN NOT NULL DEFAULT FALSE,
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
    agent_context TEXT DEFAULT '',
    is_global BOOLEAN DEFAULT FALSE
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

HOMEOSTATIC_STATE_DDL = """
CREATE TABLE IF NOT EXISTS homeostatic_state (
    domain     TEXT PRIMARY KEY,
    factor     REAL NOT NULL DEFAULT 1.0
               CHECK (factor > 0.0 AND factor < 10.0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

MEMORY_ENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id   INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (memory_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_entities_entity
    ON memory_entities (entity_id);
"""

# ── Wiki Schema (Phase 1 of redesign) ─────────────────────────────────────
# Isolated `wiki` schema. Intentionally ZERO joins from the recall hot path.
#
# Pipeline IRs stored as first-class tables, each inspectable and queryable:
#   transcript  →  claim_events  →  concepts  →  drafts  →  pages  →  rendered
#
# Survival physics match memories.heat / decay / staleness — pages EARN
# existence through citation, backlinks, access; LOSE it through idleness,
# staleness, redundancy.

WIKI_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS wiki;

-- claim_events: atomic extracted assertions from a transcript/memory.
-- Inspectable "laboratory notebook" — Hopper's nanosecond wire.
CREATE TABLE IF NOT EXISTS wiki.claim_events (
    id              BIGSERIAL PRIMARY KEY,
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    session_id      TEXT NOT NULL DEFAULT '',
    text            TEXT NOT NULL,
    claim_type      TEXT NOT NULL DEFAULT 'assertion'
                    CHECK (claim_type IN (
                      'assertion','decision','observation','question',
                      'method','result','limitation','reference'
                    )),
    entity_ids      INTEGER[] NOT NULL DEFAULT '{}',
    evidence_refs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence      REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0.0 AND confidence <= 1.0),
    embedding       vector(384),
    supersedes      BIGINT REFERENCES wiki.claim_events(id) ON DELETE SET NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- concepts: emergent candidate knowledge nodes (Strauss axial coding).
-- Sits BETWEEN memories and pages. Crystallises from entity co-occurrence
-- + embedding density. Graduates to a page on saturation.
CREATE TABLE IF NOT EXISTS wiki.concepts (
    id                      BIGSERIAL PRIMARY KEY,
    label                   TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'candidate'
                            CHECK (status IN (
                              'candidate','saturating','promoted','merged','split','abandoned'
                            )),
    centroid_embedding      vector(384),
    entity_ids              INTEGER[] NOT NULL DEFAULT '{}',
    grounding_memory_ids    INTEGER[] NOT NULL DEFAULT '{}',
    grounding_claim_ids     BIGINT[] NOT NULL DEFAULT '{}',
    properties              JSONB NOT NULL DEFAULT '{}'::jsonb,
    axial_slots             JSONB NOT NULL DEFAULT '{}'::jsonb,
    saturation_rate         REAL NOT NULL DEFAULT 1.0,
    saturation_streak       INTEGER NOT NULL DEFAULT 0,
    first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_property_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_page_id        INTEGER,
    merged_into_id          BIGINT REFERENCES wiki.concepts(id) ON DELETE SET NULL,
    split_into_ids          BIGINT[],
    core_category_link      BIGINT REFERENCES wiki.concepts(id) ON DELETE SET NULL
);

-- drafts: synthesized page content before curation.
-- Inspectable pre-render review surface.
CREATE TABLE IF NOT EXISTS wiki.drafts (
    id              BIGSERIAL PRIMARY KEY,
    concept_id      BIGINT REFERENCES wiki.concepts(id) ON DELETE CASCADE,
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL,
    lead            TEXT NOT NULL DEFAULT '',
    sections        JSONB NOT NULL DEFAULT '{}'::jsonb,
    frontmatter     JSONB NOT NULL DEFAULT '{}'::jsonb,
    provenance      JSONB NOT NULL DEFAULT '{}'::jsonb,
    synth_prompt    TEXT,
    synth_model     TEXT,
    confidence      REAL NOT NULL DEFAULT 0.5,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','published')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    published_page_id INTEGER
);

-- pages: the authored, approved wiki page (mirror of .md file).
-- Files remain source of truth — this is the facet/query index.
CREATE TABLE IF NOT EXISTS wiki.pages (
    id              SERIAL PRIMARY KEY,
    memory_id       INTEGER UNIQUE REFERENCES memories(id) ON DELETE SET NULL,
    concept_id      BIGINT REFERENCES wiki.concepts(id) ON DELETE SET NULL,
    rel_path        TEXT UNIQUE NOT NULL,
    slug            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    domains         JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
    audience        JSONB NOT NULL DEFAULT '[]'::jsonb,
    requires        JSONB NOT NULL DEFAULT '[]'::jsonb,
    status          TEXT NOT NULL DEFAULT 'seedling'
                    CHECK (status IN ('seedling','budding','evergreen')),
    lifecycle_state TEXT NOT NULL DEFAULT 'active'
                    CHECK (lifecycle_state IN ('active','area','archived','evergreen')),
    supersedes      TEXT,
    superseded_by   TEXT,
    verified        TEXT,
    lead            TEXT NOT NULL DEFAULT '',
    sections        JSONB NOT NULL DEFAULT '{}'::jsonb,
    body_hash       TEXT NOT NULL DEFAULT '',
    embedding       vector(384),
    -- thermodynamic survival physics (mirrors memories table)
    heat            REAL NOT NULL DEFAULT 1.0 CHECK (heat >= 0.0 AND heat <= 1.0),
    access_count    INTEGER NOT NULL DEFAULT 0,
    citation_count  INTEGER NOT NULL DEFAULT 0,
    backlink_count  INTEGER NOT NULL DEFAULT 0,
    source_memory_heat REAL,
    is_stale        BOOLEAN NOT NULL DEFAULT FALSE,
    planted         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tended          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ,
    last_cited_at   TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ
);

-- links: outgoing references from a page (see-also, requires, supersedes, inline).
-- Backlink lookup = reverse index by dst_page_id.
CREATE TABLE IF NOT EXISTS wiki.links (
    src_page_id     INTEGER NOT NULL REFERENCES wiki.pages(id) ON DELETE CASCADE,
    dst_slug        TEXT NOT NULL,
    dst_page_id     INTEGER REFERENCES wiki.pages(id) ON DELETE SET NULL,
    link_kind       TEXT NOT NULL DEFAULT 'see-also'
                    CHECK (link_kind IN (
                      'see-also','requires','supersedes','inline',
                      'contradicts','refines','benchmarks'
                    )),
    PRIMARY KEY (src_page_id, dst_slug, link_kind)
);

-- citations: page referenced during a Claude Code session.
-- Drives heat via trigger and is the primary authority-earning signal.
CREATE TABLE IF NOT EXISTS wiki.citations (
    id              BIGSERIAL PRIMARY KEY,
    page_id         INTEGER NOT NULL REFERENCES wiki.pages(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL DEFAULT '',
    domain          TEXT NOT NULL DEFAULT '',
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    cited_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- memos: the grounded-theory audit trail. Every curation decision
-- (merge, split, promote, abandon, reclassify) writes one row with
-- its inputs, rationale, alternatives considered, and confidence.
CREATE TABLE IF NOT EXISTS wiki.memos (
    id              BIGSERIAL PRIMARY KEY,
    subject_type    TEXT NOT NULL
                    CHECK (subject_type IN ('concept','draft','page','claim')),
    subject_id      BIGINT NOT NULL,
    decision        TEXT NOT NULL,
    rationale       TEXT NOT NULL DEFAULT '',
    alternatives    JSONB NOT NULL DEFAULT '[]'::jsonb,
    inputs          JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence      REAL NOT NULL DEFAULT 0.5,
    author          TEXT NOT NULL DEFAULT 'system',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for the likely query patterns
CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_memory
    ON wiki.claim_events (memory_id);
CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_session
    ON wiki.claim_events (session_id);
-- HNSW reloptions pinned for determinism: same (m, ef_construction) as
-- memories.embedding so benchmark reproducibility doesn't drift on
-- pgvector default changes. source: tasks/hnsw-determinism-playbook.md §1
CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_embedding
    ON wiki.claim_events USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_wiki_concepts_status
    ON wiki.concepts (status) WHERE status IN ('candidate','saturating');
CREATE INDEX IF NOT EXISTS idx_wiki_concepts_embedding
    ON wiki.concepts USING hnsw (centroid_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_wiki_drafts_status
    ON wiki.drafts (status) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_wiki_pages_kind_status_domain
    ON wiki.pages (kind, status, domain);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_lifecycle_domain
    ON wiki.pages (lifecycle_state, domain)
    WHERE lifecycle_state IN ('active','evergreen');
CREATE INDEX IF NOT EXISTS idx_wiki_pages_heat
    ON wiki.pages (heat DESC) WHERE NOT is_stale;
CREATE INDEX IF NOT EXISTS idx_wiki_pages_tags_gin
    ON wiki.pages USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_wiki_pages_embedding
    ON wiki.pages USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_wiki_links_dst
    ON wiki.links (dst_page_id) WHERE dst_page_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_wiki_links_dst_slug
    ON wiki.links (dst_slug);

CREATE INDEX IF NOT EXISTS idx_wiki_citations_page_time
    ON wiki.citations (page_id, cited_at DESC);
CREATE INDEX IF NOT EXISTS idx_wiki_citations_session
    ON wiki.citations (session_id);

CREATE INDEX IF NOT EXISTS idx_wiki_memos_subject
    ON wiki.memos (subject_type, subject_id);
"""

# Triggers and PL/pgSQL functions for the wiki schema live in a separate
# block because `_split_statements` treats any block containing `$$` as
# a single atomic unit (CREATE FUNCTION body may contain semicolons).
WIKI_TRIGGERS_DDL = """
-- Trigger: denormalise citation_count + last_cited_at + heat bump on cite
CREATE OR REPLACE FUNCTION wiki.on_citation_insert() RETURNS trigger AS $$
BEGIN
    UPDATE wiki.pages
       SET citation_count = citation_count + 1,
           last_cited_at = NEW.cited_at,
           heat = LEAST(1.0, heat + 0.05),
           tended = NEW.cited_at
     WHERE id = NEW.page_id;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_wiki_citation_bump') THEN
    CREATE TRIGGER trg_wiki_citation_bump
      AFTER INSERT ON wiki.citations
      FOR EACH ROW EXECUTE FUNCTION wiki.on_citation_insert();
  END IF;
END $$;
"""

# Separate block: link-change trigger (PL/pgSQL function with $$)
WIKI_LINK_TRIGGER_DDL = """
CREATE OR REPLACE FUNCTION wiki.on_link_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.dst_page_id IS NOT NULL THEN
        UPDATE wiki.pages SET backlink_count = backlink_count + 1
          WHERE id = NEW.dst_page_id;
    ELSIF TG_OP = 'DELETE' AND OLD.dst_page_id IS NOT NULL THEN
        UPDATE wiki.pages SET backlink_count = GREATEST(0, backlink_count - 1)
          WHERE id = OLD.dst_page_id;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.dst_page_id IS DISTINCT FROM NEW.dst_page_id THEN
            IF OLD.dst_page_id IS NOT NULL THEN
                UPDATE wiki.pages SET backlink_count = GREATEST(0, backlink_count - 1)
                  WHERE id = OLD.dst_page_id;
            END IF;
            IF NEW.dst_page_id IS NOT NULL THEN
                UPDATE wiki.pages SET backlink_count = backlink_count + 1
                  WHERE id = NEW.dst_page_id;
            END IF;
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END; $$ LANGUAGE plpgsql;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_wiki_link_change') THEN
    CREATE TRIGGER trg_wiki_link_change
      AFTER INSERT OR UPDATE OR DELETE ON wiki.links
      FOR EACH ROW EXECUTE FUNCTION wiki.on_link_change();
  END IF;
END $$;
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

CREATE TABLE IF NOT EXISTS stage_transitions (
    id                  SERIAL PRIMARY KEY,
    memory_id           INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    from_stage          TEXT NOT NULL,
    to_stage            TEXT NOT NULL,
    transitioned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hours_in_prev_stage REAL DEFAULT 0.0,
    trigger             TEXT DEFAULT 'cascade'
);
CREATE INDEX IF NOT EXISTS idx_stage_transitions_memory
    ON stage_transitions (memory_id);
CREATE INDEX IF NOT EXISTS idx_stage_transitions_time
    ON stage_transitions (transitioned_at);

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

-- Precomputed (x, y) coordinates for every workflow-graph node. The
-- layout pass runs out-of-band (handlers/recompute_layout.py via
-- igraph DrL on CPU) and persists the result here so the viz can ship
-- coordinates with each node — eliminating the d3-force tick cost in
-- the browser. ``topology_fingerprint`` tracks which graph build the
-- coordinates were computed against. The tile and quadtree endpoints
-- read them by ``layout_version`` so a stale layout never serves
-- alongside fresh nodes.
CREATE TABLE IF NOT EXISTS workflow_graph_layout (
    node_id              TEXT PRIMARY KEY,
    x                    REAL NOT NULL,
    y                    REAL NOT NULL,
    kind                 TEXT NOT NULL,
    topology_fingerprint TEXT NOT NULL,
    layout_version       BIGINT NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
CREATE INDEX IF NOT EXISTS idx_memories_heat_base
    ON memories (heat_base);
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
CREATE INDEX IF NOT EXISTS idx_workflow_graph_layout_version
    ON workflow_graph_layout (layout_version);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_layout_kind
    ON workflow_graph_layout (kind);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_layout_xy
    ON workflow_graph_layout (x, y);
"""


# ── PL/pgSQL: effective_heat (A3 lazy-heat read path) ────────────────────
#
# Source: docs/program/phase-3-a3-migration-design.md §2.
#
# Single source of truth for I1, I5, I7, I8. Pure-ish function: STABLE
# (reads wall-clock via t_now arg — planner-constant within a single
# query), PARALLEL SAFE (no session state). Output is structurally
# bounded in [stage_floor, 1.0] — I8 becomes a property of the formula,
# not a per-site LEAST guard.
#
# Preserved semantics:
#   - Stage-dependent α (Kandel 2001)
#   - Emotional damping β (Yonelinas & Ritchey 2015, Kleinsmith & Kaplan 1963)
#   - Stage floors (Bahrick 1984 permastore, Benna & Fusi 2016)
#   - p_factor (global decay rate per hour) = 0.95 default

EFFECTIVE_HEAT_FN = """
-- p_factor default: 0.95 per DAY (pre-A3 DECAY_MEMORIES_FN ran ~daily,
-- each run applied factor 0.95 once). Converted to per-hour equivalent:
-- 0.95^(1/24) ≈ 0.99787. This preserves the macroscopic decay rate while
-- making the function continuous in elapsed hours. Source:
-- docs/program/phase-3-a3-migration-design.md §2.
CREATE OR REPLACE FUNCTION effective_heat(
    m           memories,
    t_now       TIMESTAMPTZ,
    factor      REAL DEFAULT 1.0,
    p_factor    REAL DEFAULT 0.99787
) RETURNS REAL AS $$
DECLARE
    hours_elapsed  DOUBLE PRECISION;
    stage_hours    DOUBLE PRECISION;
    alpha          DOUBLE PRECISION;
    beta           DOUBLE PRECISION;
    stage_floor    DOUBLE PRECISION;
    base_scaled    DOUBLE PRECISION;
    decayed        DOUBLE PRECISION;
BEGIN
    -- Pinned: protected or explicit no_decay. heat_base is authoritative;
    -- factor still applies (homeostatic contraction affects even anchors
    -- — LEAST(1.0, …) preserves I7: protected heat never exceeds its
    -- heat_base=1.0 baseline).
    IF m.is_protected OR COALESCE(m.no_decay, FALSE) THEN
        RETURN LEAST(1.0::REAL, GREATEST(0.0::REAL, m.heat_base * factor));
    END IF;

    -- Hours since heat_base was last bumped (= last canonical touch).
    -- Falls back to last_accessed then created_at for rows migrated from
    -- pre-A3 without a heat_base_set_at value.
    hours_elapsed := GREATEST(0.0, EXTRACT(EPOCH FROM
        (t_now - COALESCE(m.heat_base_set_at, m.last_accessed, m.created_at)))
        / 3600.0);

    -- Hours since the row entered its current consolidation stage.
    -- Used by the emotional-damping β term (larger Δt_stage → β closer
    -- to 1 - 0.30·|valence|, per pg_schema.py:757-759).
    stage_hours := GREATEST(0.0, EXTRACT(EPOCH FROM
        (t_now - COALESCE(m.stage_entered_at, m.created_at))) / 3600.0);

    -- α(stage) — Kandel 2001 stage-dependent decay exponent.
    -- source: pg_schema.py:748-756
    alpha := CASE m.consolidation_stage
        WHEN 'labile'          THEN 2.0
        WHEN 'early_ltp'       THEN 1.2
        WHEN 'late_ltp'        THEN 0.8
        WHEN 'consolidated'    THEN 0.5
        WHEN 'reconsolidating' THEN 1.5
        ELSE 1.0
    END;

    -- β(valence, Δt_stage) — Yonelinas & Ritchey 2015 emotional damping.
    -- source: pg_schema.py:757-759
    --
    -- (1 - EXP(-x)) saturates to 1 for x > ~80 (EXP(-80) < 1e-34).
    -- Cap the argument at 80 to prevent EXP underflow on rows with
    -- stage_hours in the tens of thousands (e.g. benchmark fixtures
    -- with multi-year timestamps).
    beta := 1.0 - 0.30 * ABS(COALESCE(m.emotional_valence, 0.0))
                * (1.0 - EXP(-LEAST(stage_hours / 1.0, 80.0)));

    -- Stage permastore floor — Bahrick 1984 + Benna & Fusi 2016.
    -- source: pg_schema.py:742-747
    stage_floor := CASE m.consolidation_stage
        WHEN 'consolidated'    THEN 0.10
        WHEN 'late_ltp'        THEN 0.05
        WHEN 'reconsolidating' THEN 0.05
        ELSE 0.0
    END;

    -- Scale base by homeostatic factor (Feynman first-principles: factor
    -- is a scalar-per-domain gain, not a per-row mutation). Then apply
    -- decay continuously across elapsed hours:
    --   POWER(p_factor, α·β)^hours = POWER(p_factor, α·β·hours)
    --
    -- All intermediates are DOUBLE PRECISION (float8) to avoid REAL
    -- underflow at ~1e-38. The clamp below pins output ≥ stage_floor,
    -- and the final cast to REAL on RETURN lands in a safe range
    -- because POWER values < 1e-38 collapse to 0 before the cast,
    -- and GREATEST(stage_floor, 0) lifts the value back to stage_floor.
    base_scaled := m.heat_base::DOUBLE PRECISION * factor::DOUBLE PRECISION;
    decayed := base_scaled * POWER(p_factor::DOUBLE PRECISION,
                                   alpha * beta * hours_elapsed);

    -- I1 + I8: clamp to REAL-safe range BEFORE cast. REAL (float4)
    -- cannot represent values below ~1.2e-38 even as sub-normals —
    -- the cast raises NumericValueOutOfRange. stage_floor may be 0
    -- (labile), so use 1e-38 as the hard floor; downstream WRRF
    -- fusion treats 1e-38 as functionally zero (stable rank).
    decayed := LEAST(1.0::DOUBLE PRECISION,
                     GREATEST(GREATEST(stage_floor, 1e-38::DOUBLE PRECISION),
                              decayed));
    RETURN decayed::REAL;
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;
"""

# effective_heat_frozen — kill-switch alias returning heat_base directly.
# When CORTEX_MEMORY_A3_LAZY_HEAT=false at step 9 rollback, callers that
# were switched to effective_heat() can be redirected here via a runtime
# DDL swap (the function signature matches). Equivalent to the pre-A3
# eager-stored heat read.

EFFECTIVE_HEAT_FROZEN_FN = """
CREATE OR REPLACE FUNCTION effective_heat_frozen(
    m           memories,
    t_now       TIMESTAMPTZ,
    factor      REAL DEFAULT 1.0,
    p_factor    REAL DEFAULT 0.95
) RETURNS REAL AS $$
BEGIN
    -- Return heat_base directly. No decay, no factor, no stage
    -- adjustment — matches the pre-A3 stored-heat semantics exactly.
    -- Used only as an emergency rollback target when the A3 flag is
    -- flipped false but the schema has been migrated.
    RETURN LEAST(1.0, GREATEST(0.0, m.heat_base));
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
"""

# ── PL/pgSQL: recall_memories (A3 lazy-heat canonical read path) ─────────
#
# Source: docs/program/phase-3-a3-migration-design.md §4.
#
# Body:
# 1. Fetches per-domain homeostatic factor via LEFT JOIN with default 1.0.
# 2. Pre-filters a `candidates` CTE by heat_base >= p_min_heat / factor —
#    monotonic threshold transform so idx_memories_*_heat_base stays
#    usable for the prefilter.
# 3. Every CTE reads from `candidates` instead of `memories`.
# 4. Every `m.heat` reference becomes `effective_heat(m, NOW(), hs.factor)`.
# 5. Final SELECT returns `effective_heat(...)` as the `heat` output so
#    downstream Python sees the same schema.
#
# Benchmark regression gate: LongMemEval R@10 ≥ 97.8%, LoCoMo R@10 ≥ 92.6%,
# BEAM ≥ 0.543 (scores from v3.11 pre-scalability baseline, README.md).
# Because effective_heat() preserves the order relation used by the hot
# CTE (positive factor + monotonic decay curve), the top-N hot memories
# remain the same on fresh stores where factor=1.0 and all memories have
# hours_elapsed=0 (benchmark fixtures load memories with synthetic timestamps).

RECALL_MEMORIES_LAZY_FN = """
DROP FUNCTION IF EXISTS recall_memories(
    TEXT, vector, TEXT, TEXT, TEXT, TEXT, REAL, INT, INT,
    REAL, REAL, REAL, REAL, REAL, BOOLEAN
);
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
    p_w_heat        REAL DEFAULT 0.3,
    p_w_ngram       REAL DEFAULT 0.3,
    p_w_recency     REAL DEFAULT 0.0,
    p_include_globals BOOLEAN DEFAULT TRUE
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
    surprise_score  REAL,
    emotional_valence REAL,
    source          TEXT
) AS $$
DECLARE
    v_pool   INT := p_max_results * 10;
    v_factor REAL;
    v_words  TEXT[] := regexp_split_to_array(
        regexp_replace(lower(p_query_text), '[^a-z0-9 ]', ' ', 'g'),
        '\\s+'
    );
    v_or_expr TEXT := array_to_string(
        ARRAY(SELECT w FROM unnest(v_words) w WHERE length(w) > 1),
        ' | '
    );
    v_tsq  tsquery := CASE WHEN v_or_expr = '' THEN plainto_tsquery('english', p_query_text)
                            ELSE to_tsquery('english', v_or_expr) END;
    v_min_heat_base REAL;
BEGIN
    -- Resolve the homeostatic factor for this domain (1.0 default).
    SELECT COALESCE(MAX(hs.factor), 1.0) INTO v_factor
    FROM homeostatic_state hs
    WHERE hs.domain = COALESCE(p_domain, '');

    -- Prefilter threshold: heat_base >= p_min_heat / factor is the
    -- monotonic transform that preserves ordering (Zhuangzi: positive
    -- factor preserves the order relation on heat_base). Index usable.
    v_min_heat_base := p_min_heat / GREATEST(v_factor, 0.001);

    RETURN QUERY
    WITH
    -- Prefilter: narrow memories by cheap heat_base threshold + stale/
    -- domain/directory gates. All downstream CTEs read `candidates` not
    -- `memories` — that's where the WRRF fusion signal-processing happens.
    candidates AS (
        SELECT m.*
        FROM memories m
        WHERE m.heat_base >= v_min_heat_base
          AND NOT m.is_stale
          AND (p_domain IS NULL
               OR m.domain = p_domain
               OR (p_include_globals AND m.is_global = TRUE))
          AND (p_directory IS NULL OR m.directory_context = p_directory)
    ),
    -- Signal 1: Vector cosine similarity (pgvector)
    vec AS (
        SELECT c.id,
               (1.0 - (c.embedding <=> p_query_emb))::REAL AS raw_score
        FROM candidates c
        WHERE c.embedding IS NOT NULL
          AND effective_heat(c, NOW(), v_factor) >= p_min_heat
        ORDER BY c.embedding <=> p_query_emb
        LIMIT v_pool
    ),
    -- Signal 2: Full-text search
    fts AS (
        SELECT c.id,
               ts_rank_cd(c.content_tsv, v_tsq)::REAL AS raw_score
        FROM candidates c
        WHERE c.content_tsv @@ v_tsq
          AND effective_heat(c, NOW(), v_factor) >= p_min_heat
        ORDER BY ts_rank_cd(c.content_tsv, v_tsq) DESC
        LIMIT v_pool
    ),
    -- Signal 3: Trigram similarity
    ngram AS (
        SELECT c.id,
               similarity(c.content, p_query_text)::REAL AS raw_score
        FROM candidates c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
          AND similarity(c.content, p_query_text) > 0.1
        ORDER BY similarity(c.content, p_query_text) DESC
        LIMIT v_pool
    ),
    -- Signal 4: Heat (now lazy via effective_heat). Post-A3 the hot CTE
    -- orders by effective_heat directly; the B-tree on heat_base is still
    -- used by the prefilter, so this is NOT a full candidates scan —
    -- candidates is already bounded.
    hot AS (
        SELECT c.id,
               effective_heat(c, NOW(), v_factor) AS raw_score
        FROM candidates c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
        ORDER BY effective_heat(c, NOW(), v_factor) DESC
        LIMIT v_pool
    ),
    -- Signal 5: Recency via exponential decay
    recency AS (
        SELECT c.id,
               EXP(-0.01 * EXTRACT(EPOCH FROM (NOW() - c.created_at)) / 86400.0)::REAL AS raw_score
        FROM candidates c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
        ORDER BY c.created_at DESC
        LIMIT v_pool
    ),
    -- Per-signal observed max for TMM normalization (Bruch 2023)
    vec_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM vec),
    fts_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM fts),
    ng_max   AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM ngram),
    hot_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM hot),
    rec_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM recency),
    fused AS (
        SELECT id, SUM(contribution) AS fused_score
        FROM (
            SELECT v.id,
                   p_w_vector * (v.raw_score - (-1.0)) / GREATEST(b.hi - (-1.0), 0.001) AS contribution
            FROM vec v, vec_max b
            UNION ALL
            SELECT f.id,
                   p_w_fts * f.raw_score / GREATEST(b.hi, 0.001)
            FROM fts f, fts_max b
            UNION ALL
            SELECT n.id,
                   p_w_ngram * n.raw_score / GREATEST(b.hi, 0.001)
            FROM ngram n, ng_max b
            UNION ALL
            SELECT h.id,
                   p_w_heat * h.raw_score / GREATEST(b.hi, 0.001)
            FROM hot h, hot_max b
            UNION ALL
            SELECT r.id,
                   p_w_recency * r.raw_score / GREATEST(b.hi, 0.001)
            FROM recency r, rec_max b
            WHERE p_w_recency > 0
        ) signals
        GROUP BY id
    ),
    agent_boosted AS (
        SELECT f.id,
               CASE WHEN p_agent_topic IS NOT NULL
                         AND c.agent_context = p_agent_topic
                    THEN f.fused_score + 0.3 * (p_w_vector / p_wrrf_k)
                    ELSE f.fused_score
               END AS boosted_score
        FROM fused f
        JOIN candidates c ON c.id = f.id
    ),
    emotional_boosted AS (
        SELECT ab.id,
               ab.boosted_score * (
                   1.0 + ABS(COALESCE(c.emotional_valence, 0.0)) * 0.15
                   * (1.0 - EXP(-EXTRACT(EPOCH FROM (NOW() - c.created_at)) / 3600.0))
               ) AS emo_score
        FROM agent_boosted ab
        JOIN candidates c ON c.id = ab.id
    ),
    tag_boosted AS (
        SELECT eb.id,
               eb.emo_score * (
                   1.0 + CASE
                       WHEN p_intent IN ('preference', 'instruction')
                            AND c.tags @> to_jsonb(p_intent::TEXT)
                       THEN 0.4
                       ELSE 0.0
                   END
               ) AS final_score
        FROM emotional_boosted eb
        JOIN candidates c ON c.id = eb.id
    )
    SELECT tb.id,
           c.content,
           tb.final_score::REAL,
           effective_heat(c, NOW(), v_factor)::REAL AS heat,
           c.domain,
           c.created_at,
           c.store_type,
           c.tags,
           c.importance,
           c.surprise_score,
           c.emotional_valence,
           c.source
    FROM tag_boosted tb
    JOIN candidates c ON c.id = tb.id
    ORDER BY tb.final_score DESC
    LIMIT p_max_results * 3;
END;
$$ LANGUAGE plpgsql STABLE;
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
        WHERE m.heat_base >= p_min_heat AND NOT m.is_stale
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
    SELECT m.id, m.embedding, effective_heat(m, NOW(), 1.0)
    FROM memories m
    WHERE m.heat_base >= p_min_heat
      AND NOT m.is_stale
      AND m.embedding IS NOT NULL
      AND (p_domain IS NULL OR m.domain = p_domain OR (p_include_globals AND m.is_global = TRUE))
    ORDER BY m.heat_base DESC
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
-- A3 rename: heat column -> heat_base. Idempotent: only renames when
-- the old column still exists. After rename, add heat_base_set_at +
-- no_decay columns if missing. Source: docs/program/phase-3-a3-migration-design.md §1.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'heat'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'heat_base'
    ) THEN
        ALTER TABLE memories RENAME COLUMN heat TO heat_base;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'heat_base_set_at'
    ) THEN
        ALTER TABLE memories ADD COLUMN heat_base_set_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        UPDATE memories SET heat_base_set_at = COALESCE(last_accessed, created_at, NOW());
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'no_decay'
    ) THEN
        ALTER TABLE memories ADD COLUMN no_decay BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
END $$;

-- Phase 2 B3 migration: canonicalize co_retrieval relationships so
-- (min(source,target), max(source,target), 'co_retrieval') is unique.
-- Step 1: rewrite reverse-direction rows to canonical order, summing
-- weight with the canonical-direction row if present.
-- Step 2: delete the now-duplicate reverse rows.
-- Step 3: add the UNIQUE constraint. Idempotent via IF NOT EXISTS.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'uq_relationships_canonical_co_retrieval'
    ) THEN
        -- Step 1+2: dedup reverse direction rows.
        WITH canonical AS (
            SELECT LEAST(source_entity_id, target_entity_id) AS a,
                   GREATEST(source_entity_id, target_entity_id) AS b,
                   relationship_type,
                   SUM(weight) AS total_weight,
                   MAX(facilitation) AS max_facilitation,
                   MAX(last_reinforced) AS last_reinforced,
                   MIN(id) AS keep_id
            FROM relationships
            WHERE relationship_type = 'co_retrieval'
            GROUP BY LEAST(source_entity_id, target_entity_id),
                     GREATEST(source_entity_id, target_entity_id),
                     relationship_type
        )
        UPDATE relationships r
        SET source_entity_id = c.a,
            target_entity_id = c.b,
            weight = LEAST(2.0, c.total_weight),
            facilitation = LEAST(1.0, c.max_facilitation),
            last_reinforced = c.last_reinforced
        FROM canonical c
        WHERE r.id = c.keep_id;

        DELETE FROM relationships r
        USING (
            SELECT id, relationship_type,
                   LEAST(source_entity_id, target_entity_id) AS a,
                   GREATEST(source_entity_id, target_entity_id) AS b
            FROM relationships
            WHERE relationship_type = 'co_retrieval'
        ) dup
        WHERE r.id = dup.id
          AND r.relationship_type = 'co_retrieval'
          AND (r.source_entity_id, r.target_entity_id) <> (dup.a, dup.b);

        -- Step 3: UNIQUE constraint.
        CREATE UNIQUE INDEX uq_relationships_canonical_co_retrieval
            ON relationships (source_entity_id, target_entity_id, relationship_type)
            WHERE relationship_type = 'co_retrieval';
    END IF;
END $$;

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

-- Partial index for fast non-benchmark queries (A3: heat_base ordered)
CREATE INDEX IF NOT EXISTS idx_memories_not_benchmark
    ON memories (heat_base DESC) WHERE NOT is_benchmark;

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

-- Migration: add is_global column for cross-project memory sharing
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'is_global'
    ) THEN
        ALTER TABLE memories ADD COLUMN is_global BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_memories_is_global
    ON memories (is_global) WHERE is_global = TRUE;

-- Migration: add stage_entered_at for real-time cascade tracking
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'stage_entered_at'
    ) THEN
        ALTER TABLE memories ADD COLUMN stage_entered_at TIMESTAMPTZ;
        -- Backfill: set to created_at for existing memories
        UPDATE memories SET stage_entered_at = created_at WHERE stage_entered_at IS NULL;
    END IF;
END $$;

-- Migration: persist arousal and dominant_emotion from emotional tagging
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='arousal')
    THEN ALTER TABLE memories ADD COLUMN arousal REAL NOT NULL DEFAULT 0.0 CHECK (arousal >= 0.0 AND arousal <= 1.0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='memories' AND column_name='dominant_emotion')
    THEN ALTER TABLE memories ADD COLUMN dominant_emotion TEXT NOT NULL DEFAULT 'neutral'
        CHECK (dominant_emotion IN ('frustration','satisfaction','confusion','urgency','discovery','neutral'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_memories_dominant_emotion
    ON memories (dominant_emotion) WHERE dominant_emotion != 'neutral';

-- Migration: domain normalization trigger
CREATE OR REPLACE FUNCTION normalize_domain() RETURNS trigger AS $$
BEGIN
    NEW.domain := LOWER(COALESCE(NEW.domain, ''));
    IF NEW.domain IN ('jarvis', 'cortex-cowork') THEN NEW.domain := 'cortex'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_memories_domain_normalize') THEN
        CREATE TRIGGER trg_memories_domain_normalize BEFORE INSERT OR UPDATE OF domain ON memories
        FOR EACH ROW EXECUTE FUNCTION normalize_domain();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_entities_domain_normalize') THEN
        CREATE TRIGGER trg_entities_domain_normalize BEFORE INSERT OR UPDATE OF domain ON entities
        FOR EACH ROW EXECUTE FUNCTION normalize_domain();
    END IF;
END $$;
"""

# ── Schema initialization ────────────────────────────────────────────────


def _split_statements(ddl: str) -> list[str]:
    """Split a multi-statement DDL string into individual statements.

    Handles CREATE FUNCTION blocks that contain semicolons in the
    body by detecting $$ delimiters.
    """
    if "$$" in ddl:
        # PL/pgSQL function — return as single block
        return [ddl.strip()] if ddl.strip() else []
    statements = []
    for part in ddl.split(";"):
        stmt = part.strip()
        if stmt:
            statements.append(stmt + ";")
    return statements


def get_all_ddl() -> list[str]:
    """Return all DDL as individual statements for safe per-statement execution.

    Each statement can be executed independently — if one fails, the
    rest still run. This prevents a single column type error from
    silently skipping 7 subsequent table creations.
    """
    blocks = [
        EXTENSIONS_DDL,
        MEMORIES_DDL,
        HOMEOSTATIC_STATE_DDL,
        ENTITIES_DDL,
        RELATIONSHIPS_DDL,
        MEMORY_ENTITIES_DDL,
        WIKI_SCHEMA_DDL,
        WIKI_TRIGGERS_DDL,
        WIKI_LINK_TRIGGER_DDL,
        SUPPORT_TABLES_DDL,
        # MIGRATIONS_DDL runs BEFORE INDEXES_DDL so the heat→heat_base
        # rename lands before indexes on heat_base are created.
        MIGRATIONS_DDL,
        INDEXES_DDL,
        EFFECTIVE_HEAT_FN,
        EFFECTIVE_HEAT_FROZEN_FN,
        # A3 canonical read path: lazy effective_heat() computes decay at
        # read time; RECALL_MEMORIES_LAZY_FN replaces the eager legacy
        # recall_memories() + decay_memories() entirely.
        RECALL_MEMORIES_LAZY_FN,
        SPREAD_ACTIVATION_FN,
        SPREAD_ACTIVATION_MEMORIES_FN,
        GET_HOT_EMBEDDINGS_FN,
        GET_TEMPORAL_CO_ACCESS_FN,
    ]
    result: list[str] = []
    for block in blocks:
        result.extend(_split_statements(block))
    return result
