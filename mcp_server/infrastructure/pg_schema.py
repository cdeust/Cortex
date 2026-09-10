"""PostgreSQL schema: DDL, extensions, stored procedures, migrations.

Pure DDL — no connection management.

source: ADR-0537"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing_extensions import LiteralString

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
    content_tsv     tsvector GENERATED ALWAYS AS
                        (to_tsvector('english', content)) STORED,
    tags            JSONB DEFAULT '[]'::jsonb,
    source          TEXT DEFAULT '',
    domain          TEXT DEFAULT '',
    directory_context TEXT DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
    value           REAL DEFAULT 0.5,
    source_attribution TEXT DEFAULT 'unknown',
    capture_origin  TEXT NOT NULL DEFAULT 'unknown',
    stimulus_signature TEXT DEFAULT '',
    extinction_strength REAL DEFAULT 0.0
                    CHECK (extinction_strength >= 0.0 AND extinction_strength <= 1.0),
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
    is_global BOOLEAN DEFAULT FALSE,
    supersedes_id   INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    superseded_by_id INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    -- source: ADR-0537
    write_class     TEXT NOT NULL DEFAULT 'deliberate'
                    CHECK (write_class IN
                        ('auto', 'deliberate', 'derived', 'mechanical'))
);
"""

# source: ADR-0537
MEMORIES_STORAGE_OPTIONS_DDL = """
ALTER TABLE memories SET (autovacuum_vacuum_scale_factor = 0.05);
"""

# source: ADR-0537
CURRENT_MEMORIES_VIEW_DDL = """
CREATE OR REPLACE VIEW current_memories AS
    SELECT * FROM memories WHERE superseded_by_id IS NULL;
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
    archived        BOOLEAN DEFAULT FALSE,
    -- source: ADR-0537
    origin          TEXT NOT NULL DEFAULT 'text_concept'
                    CHECK (origin IN ('ast_symbol', 'text_concept'))
);
"""

HOMEOSTATIC_STATE_DDL = """
-- source: ADR-0537
CREATE TABLE IF NOT EXISTS homeostatic_state (
    domain      TEXT NOT NULL,
    write_class TEXT NOT NULL DEFAULT 'auto'
                CHECK (write_class IN ('auto', 'deliberate', 'derived', 'mechanical')),
    factor      REAL NOT NULL DEFAULT 1.0
                CHECK (factor > 0.0 AND factor < 10.0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain, write_class)
);

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS homeostatic_fold_log (
    id          SERIAL PRIMARY KEY,
    domain      TEXT NOT NULL,
    write_class TEXT NOT NULL,
    factor      REAL NOT NULL,
    rows_folded INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_homeostatic_fold_log_domain_class
    ON homeostatic_fold_log (domain, write_class, created_at DESC);
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

# source: ADR-0537

WIKI_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS wiki;

-- source: ADR-0537
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
    confidence      REAL NOT NULL DEFAULT 0.5
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    embedding       vector(384),
    supersedes      BIGINT REFERENCES wiki.claim_events(id) ON DELETE SET NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- source: ADR-0537
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

-- source: ADR-0537
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

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS wiki.pages (
    id              SERIAL PRIMARY KEY,
    memory_id       INTEGER UNIQUE REFERENCES memories(id) ON DELETE SET NULL,
    concept_id      BIGINT REFERENCES wiki.concepts(id) ON DELETE SET NULL,
    -- source: ADR-0537
    documents_primary TEXT,
    rel_path        TEXT UNIQUE NOT NULL,
    slug            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    domains         JSONB NOT NULL DEFAULT '[]'::jsonb,
    tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
    audience        JSONB NOT NULL DEFAULT '[]'::jsonb,
    requires        JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- source: ADR-0537
    status          TEXT NOT NULL DEFAULT 'seedling'
                    CHECK (status IN (
                      'seedling','budding','evergreen','living',
                      'proposed','accepted','rejected','deprecated','superseded',
                      'draft','review','implemented'
                    )),
    lifecycle_state TEXT NOT NULL DEFAULT 'active'
                    CHECK (lifecycle_state IN ('active','area','archived','evergreen')),
    supersedes      TEXT,
    superseded_by   TEXT,
    verified        TEXT,
    lead            TEXT NOT NULL DEFAULT '',
    sections        JSONB NOT NULL DEFAULT '{}'::jsonb,
    body_hash       TEXT NOT NULL DEFAULT '',
    embedding       vector(384),
    -- source: ADR-0537
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

-- source: ADR-0537
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

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS wiki.citations (
    id              BIGSERIAL PRIMARY KEY,
    page_id         INTEGER NOT NULL REFERENCES wiki.pages(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL DEFAULT '',
    domain          TEXT NOT NULL DEFAULT '',
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    cited_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS wiki.page_sources (
    page_id         INTEGER NOT NULL REFERENCES wiki.pages(id) ON DELETE CASCADE,
    source_path     TEXT NOT NULL,
    symbol          TEXT,
    link_kind       TEXT NOT NULL DEFAULT 'documents'
                    -- source: ADR-0537
                    CHECK (link_kind IN (
                      'documents','references','derived','finding','extracted_from'
                    )),
    confidence      REAL NOT NULL DEFAULT 1.0,
    source          TEXT NOT NULL DEFAULT 'frontmatter'
                    -- source: ADR-0537
                    CHECK (source IN (
                      'frontmatter','claim_evidence','body','codebase_grounding',
                      'ap-pipeline'
                    )),
    PRIMARY KEY (page_id, source_path, link_kind)
);

-- source: ADR-0537
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

-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_memory
    ON wiki.claim_events (memory_id);
CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_session
    ON wiki.claim_events (session_id);
-- source: ADR-0537
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

-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_wiki_page_sources_path
    ON wiki.page_sources (source_path);

CREATE INDEX IF NOT EXISTS idx_wiki_citations_page_time
    ON wiki.citations (page_id, cited_at DESC);
CREATE INDEX IF NOT EXISTS idx_wiki_citations_session
    ON wiki.citations (session_id);

CREATE INDEX IF NOT EXISTS idx_wiki_memos_subject
    ON wiki.memos (subject_type, subject_id);
"""

# source: ADR-0537
WIKI_TRIGGERS_DDL = """
-- source: ADR-0537
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
    triggered_count     INTEGER DEFAULT 0,
    created_by          TEXT NOT NULL DEFAULT '',
    -- source: ADR-0537
    source_memory_id    INTEGER
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

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS injection_receipts (
    id                  SERIAL PRIMARY KEY,
    session_id          TEXT,
    channel             TEXT NOT NULL
        CONSTRAINT injection_receipts_channel_enum CHECK (
            channel IN ('recall', 'session_start', 'auto_recall', 'agent_briefing')
        ),
    emitted_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_injection_receipts_session
    ON injection_receipts (session_id);
CREATE INDEX IF NOT EXISTS idx_injection_receipts_time
    ON injection_receipts (emitted_at);

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS injection_receipt_items (
    id                  SERIAL PRIMARY KEY,
    receipt_id          INTEGER NOT NULL
                        REFERENCES injection_receipts(id) ON DELETE CASCADE,
    memory_id           INTEGER NOT NULL,
    rank                INTEGER NOT NULL,
    score               REAL
);
CREATE INDEX IF NOT EXISTS idx_injection_receipt_items_receipt
    ON injection_receipt_items (receipt_id);
CREATE INDEX IF NOT EXISTS idx_injection_receipt_items_memory
    ON injection_receipt_items (memory_id);

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
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- source: ADR-0537
    source_memory_id    INTEGER
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

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS user_mood (
    user_id     TEXT PRIMARY KEY DEFAULT 'default',
    valence     REAL NOT NULL DEFAULT 0.0
        CHECK (valence >= -1.0 AND valence <= 1.0),
    arousal     REAL NOT NULL DEFAULT 0.0
        CHECK (arousal >= -1.0 AND arousal <= 1.0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO user_mood (user_id, valence, arousal) VALUES ('default', 0.0, 0.0)
ON CONFLICT (user_id) DO NOTHING;

-- source: ADR-0537
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

# source: ADR-0537
PROCEDURAL_SKILLS_DDL = """
CREATE TABLE IF NOT EXISTS procedural_skills (
    id                  SERIAL PRIMARY KEY,
    skill_id            TEXT NOT NULL UNIQUE,
    action_sequence     TEXT NOT NULL,
    context_signature   TEXT NOT NULL DEFAULT '',
    occurrences         INTEGER NOT NULL DEFAULT 0,
    success_count       INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    proficiency         REAL NOT NULL DEFAULT 0.0,
    is_habitual         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# ── Indexes ───────────────────────────────────────────────────────────────

INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_memories_content_tsv
    ON memories USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
    ON memories USING gin (content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_memories_heat_base
    ON memories (heat_base);
-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_memories_heat_base_id
    ON memories (heat_base DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_memories_domain
    ON memories (domain);
-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_memories_domain_write_class
    ON memories (domain, write_class);
CREATE INDEX IF NOT EXISTS idx_memories_store_type
    ON memories (store_type);
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at);
-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_memories_curated_heat_base
    ON memories (heat_base)
    WHERE source <> 'post_tool_capture' AND NOT is_stale
      AND superseded_by_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_memories_curated_created_at
    ON memories (created_at DESC)
    WHERE source <> 'post_tool_capture' AND NOT is_stale
      AND superseded_by_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_memories_stage
    ON memories (consolidation_stage);
-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_memories_tags_gin
    ON memories USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_entities_name
    ON entities (name);
CREATE INDEX IF NOT EXISTS idx_entities_heat
    ON entities (heat);
CREATE INDEX IF NOT EXISTS idx_prospective_active
    ON prospective_memories (is_active);
CREATE INDEX IF NOT EXISTS idx_procedural_context
    ON procedural_skills (context_signature);
CREATE INDEX IF NOT EXISTS idx_procedural_proficiency
    ON procedural_skills (proficiency DESC);
CREATE INDEX IF NOT EXISTS idx_schemas_domain
    ON schemas (domain);
CREATE INDEX IF NOT EXISTS idx_rel_pair_type
    ON relationships (source_entity_id, target_entity_id, relationship_type);
CREATE INDEX IF NOT EXISTS idx_memories_agent_context
    ON memories (agent_context);
-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_memories_superseded_by
    ON memories (superseded_by_id) WHERE superseded_by_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_supersedes
    ON memories (supersedes_id) WHERE supersedes_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_workflow_graph_layout_version
    ON workflow_graph_layout (layout_version);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_layout_kind
    ON workflow_graph_layout (kind);
CREATE INDEX IF NOT EXISTS idx_workflow_graph_layout_xy
    ON workflow_graph_layout (x, y);
"""


# source: ADR-0537

EFFECTIVE_STAGE_FN = """
-- source: ADR-0537
CREATE OR REPLACE FUNCTION effective_stage(
    p_stage      TEXT,
    p_hours      DOUBLE PRECISION,
    p_importance REAL,
    p_access     INTEGER,
    p_schema     REAL
) RETURNS TEXT AS $$
DECLARE
    cur      TEXT             := p_stage;
    budget   DOUBLE PRECISION := GREATEST(0.0, COALESCE(p_hours, 0.0));
    imp      DOUBLE PRECISION := COALESCE(p_importance, 0.5);
    acc      INTEGER          := COALESCE(p_access, 0);
    sch      DOUBLE PRECISION := COALESCE(p_schema, 0.0);
    dwell    DOUBLE PRECISION;
    late_thr INTEGER;
BEGIN
    -- source: ADR-0537
    IF cur NOT IN ('labile', 'early_ltp', 'late_ltp', 'consolidated') THEN
        RETURN cur;
    END IF;

    -- source: ADR-0537
    IF cur = 'labile' THEN
        IF imp > 0.3 THEN
            cur := 'early_ltp';
        ELSE
            RETURN cur;
        END IF;
    END IF;

    -- source: ADR-0537
    IF cur = 'early_ltp' THEN
        dwell := 1.0 * (1.0 - sch * 0.2);
        IF budget >= dwell AND (acc >= 1 OR imp > 0.4) THEN
            budget := budget - dwell;
            cur := 'late_ltp';
        ELSE
            RETURN cur;
        END IF;
    END IF;

    -- source: ADR-0537
    IF cur = 'late_ltp' THEN
        dwell := 6.0 * POWER(15.0, -sch);
        late_thr := CASE WHEN sch < 0.5 THEN 3 ELSE 1 END;
        IF budget >= dwell AND acc >= late_thr THEN
            cur := 'consolidated';
        END IF;
    END IF;

    -- source: ADR-0537
    RETURN cur;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
"""

ALPHA_INTEGRAL_FN = """
-- source: ADR-0537
CREATE OR REPLACE FUNCTION alpha_integral(
    p_stage      TEXT,
    p_tau        DOUBLE PRECISION,
    p_importance REAL,
    p_access     INTEGER,
    p_schema     REAL
) RETURNS DOUBLE PRECISION AS $$
DECLARE
    cur       TEXT             := p_stage;
    remaining DOUBLE PRECISION := GREATEST(0.0, COALESCE(p_tau, 0.0));
    imp       DOUBLE PRECISION := COALESCE(p_importance, 0.5);
    acc       INTEGER          := COALESCE(p_access, 0);
    sch       DOUBLE PRECISION := COALESCE(p_schema, 0.0);
    total     DOUBLE PRECISION := 0.0;
    dwell     DOUBLE PRECISION;
    late_thr  INTEGER;
    seg       DOUBLE PRECISION;
BEGIN
    -- source: ADR-0537
    IF cur NOT IN ('labile', 'early_ltp', 'late_ltp', 'consolidated') THEN
        RETURN (CASE cur WHEN 'reconsolidating' THEN 1.5 ELSE 1.0 END)
               * remaining;
    END IF;

    -- source: ADR-0537
    IF cur = 'labile' THEN
        IF imp > 0.3 THEN
            cur := 'early_ltp';
        ELSE
            RETURN total + 2.0 * remaining;
        END IF;
    END IF;

    -- source: ADR-0537
    IF cur = 'early_ltp' THEN
        dwell := 1.0 * (1.0 - sch * 0.2);
        IF NOT (acc >= 1 OR imp > 0.4) THEN
            RETURN total + 1.2 * remaining;
        END IF;
        seg := LEAST(remaining, dwell);
        total := total + 1.2 * seg;
        remaining := remaining - seg;
        IF remaining <= 0.0 THEN RETURN total; END IF;
        cur := 'late_ltp';
    END IF;

    -- source: ADR-0537
    IF cur = 'late_ltp' THEN
        dwell := 6.0 * POWER(15.0, -sch);
        late_thr := CASE WHEN sch < 0.5 THEN 3 ELSE 1 END;
        IF NOT (acc >= late_thr) THEN
            RETURN total + 0.8 * remaining;
        END IF;
        seg := LEAST(remaining, dwell);
        total := total + 0.8 * seg;
        remaining := remaining - seg;
        IF remaining <= 0.0 THEN RETURN total; END IF;
        cur := 'consolidated';
    END IF;

    -- source: ADR-0537
    RETURN total + 0.5 * remaining;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
"""

EFFECTIVE_HEAT_FN = """
-- source: ADR-0537
CREATE OR REPLACE FUNCTION effective_heat(
    m           memories,
    t_now       TIMESTAMPTZ,
    factor      REAL DEFAULT 1.0,
    p_factor    REAL DEFAULT 0.99787
) RETURNS REAL AS $$
DECLARE
    hours_elapsed  DOUBLE PRECISION;
    stage_hours    DOUBLE PRECISION;
    beta           DOUBLE PRECISION;
    stage_floor    DOUBLE PRECISION;
    base_scaled    DOUBLE PRECISION;
    decayed        DOUBLE PRECISION;
    eff_decay_hours DOUBLE PRECISION;
    eff_stage      TEXT;
BEGIN
    -- source: ADR-0537
    IF m.is_protected OR COALESCE(m.no_decay, FALSE) THEN
        RETURN LEAST(1.0::REAL, GREATEST(0.0::REAL, m.heat_base * factor));
    END IF;

    -- source: ADR-0537
    hours_elapsed := GREATEST(0.0, EXTRACT(EPOCH FROM
        (t_now - COALESCE(m.heat_base_set_at, m.last_accessed, m.created_at)))
        / 3600.0);

    -- source: ADR-0537
    stage_hours := GREATEST(0.0, EXTRACT(EPOCH FROM
        (t_now - COALESCE(m.stage_entered_at, m.created_at))) / 3600.0);

    -- source: ADR-0537
    eff_stage := effective_stage(
        m.consolidation_stage,
        stage_hours,
        m.importance,
        m.access_count,
        m.schema_match_score
    );

    -- source: ADR-0537
    beta := 1.0 - 0.30 * ABS(COALESCE(m.emotional_valence, 0.0))
                * (1.0 - EXP(-LEAST(stage_hours / 1.0, 80.0)));

    -- source: ADR-0537
    stage_floor := CASE eff_stage
        WHEN 'consolidated'    THEN 0.10
        WHEN 'late_ltp'        THEN 0.05
        WHEN 'reconsolidating' THEN 0.05
        ELSE 0.0
    END;

    -- source: ADR-0537
    eff_decay_hours :=
        alpha_integral(m.consolidation_stage, stage_hours,
                       m.importance, m.access_count, m.schema_match_score)
        - alpha_integral(m.consolidation_stage,
                         GREATEST(0.0, stage_hours - hours_elapsed),
                         m.importance, m.access_count, m.schema_match_score);

    -- source: ADR-0537
    base_scaled := m.heat_base::DOUBLE PRECISION * factor::DOUBLE PRECISION;
    decayed := base_scaled * POWER(p_factor::DOUBLE PRECISION,
                                   beta * eff_decay_hours);

    -- source: ADR-0537
    decayed := LEAST(1.0::DOUBLE PRECISION,
                     GREATEST(GREATEST(stage_floor, 1e-38::DOUBLE PRECISION),
                              decayed));
    RETURN decayed::REAL;
END;
$$ LANGUAGE plpgsql STABLE PARALLEL SAFE;
"""

# source: ADR-0537

EFFECTIVE_HEAT_FROZEN_FN = """
CREATE OR REPLACE FUNCTION effective_heat_frozen(
    m           memories,
    t_now       TIMESTAMPTZ,
    factor      REAL DEFAULT 1.0,
    p_factor    REAL DEFAULT 0.95
) RETURNS REAL AS $$
BEGIN
    -- source: ADR-0537
    RETURN LEAST(1.0, GREATEST(0.0, m.heat_base));
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
"""

# source: ADR-0537

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
    p_include_globals BOOLEAN DEFAULT TRUE,
    -- source: ADR-0537
    p_trusted_origins TEXT[] DEFAULT ARRAY[]::TEXT[],
    p_untrusted_factor REAL DEFAULT 1.0
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
    source          TEXT,
    value           REAL,
    source_attribution TEXT,
    -- source: ADR-0537
    capture_origin  TEXT
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
    v_tsq  tsquery := CASE WHEN v_or_expr = ''
                            THEN plainto_tsquery('english', p_query_text)
                            ELSE to_tsquery('english', v_or_expr) END;
    v_min_heat_base REAL;
BEGIN
    -- source: ADR-0537
    SELECT COALESCE(MAX(hs.factor), 1.0) INTO v_factor
    FROM homeostatic_state hs
    WHERE hs.domain = COALESCE(p_domain, '') AND hs.write_class = 'auto';

    -- source: ADR-0537
    v_min_heat_base := p_min_heat / GREATEST(v_factor, 0.001);

    RETURN QUERY
    WITH
    -- source: ADR-0537
    eligible AS NOT MATERIALIZED (
        SELECT m.*
        FROM current_memories m
        WHERE m.heat_base >= v_min_heat_base
          AND NOT m.is_stale
          AND (p_domain IS NULL
               OR m.domain = p_domain
               OR (p_include_globals AND m.is_global = TRUE))
          AND (p_directory IS NULL OR m.directory_context = p_directory)
    ),
    -- source: ADR-0537
    vec AS (
        SELECT c.id,
               (1.0 - (c.embedding <=> p_query_emb))::REAL AS raw_score
        FROM eligible c
        WHERE c.embedding IS NOT NULL
          AND effective_heat(c, NOW(), v_factor) >= p_min_heat
        ORDER BY c.embedding <=> p_query_emb
        LIMIT v_pool
    ),
    -- source: ADR-0537
    fts AS (
        SELECT c.id,
               ts_rank_cd(c.content_tsv, v_tsq)::REAL AS raw_score
        FROM eligible c
        WHERE c.content_tsv @@ v_tsq
          AND effective_heat(c, NOW(), v_factor) >= p_min_heat
        ORDER BY ts_rank_cd(c.content_tsv, v_tsq) DESC
        LIMIT v_pool
    ),
    -- source: ADR-0537
    ngram AS (
        SELECT c.id,
               similarity(c.content, p_query_text)::REAL AS raw_score
        FROM eligible c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
          AND c.content % p_query_text
          AND similarity(c.content, p_query_text) > 0.1
        ORDER BY similarity(c.content, p_query_text) DESC
        LIMIT v_pool
    ),
    -- source: ADR-0537
    hot AS (
        SELECT c.id,
               effective_heat(c, NOW(), v_factor) AS raw_score
        FROM eligible c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
          AND c.source <> 'post_tool_capture'
        ORDER BY effective_heat(c, NOW(), v_factor) DESC
        LIMIT v_pool
    ),
    -- source: ADR-0537
    recency AS (
        SELECT c.id,
               EXP(-0.01 * EXTRACT(EPOCH FROM (NOW() - c.created_at))
                   / 86400.0)::REAL AS raw_score
        FROM eligible c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
          AND c.source <> 'post_tool_capture'
        ORDER BY c.created_at DESC
        LIMIT v_pool
    ),
    -- source: ADR-0537
    candidates AS MATERIALIZED (
        SELECT m.* FROM current_memories m
        JOIN (
            SELECT id FROM vec UNION SELECT id FROM fts
            UNION SELECT id FROM ngram UNION SELECT id FROM hot
            UNION SELECT id FROM recency
        ) pool_ids ON pool_ids.id = m.id
    ),
    -- source: ADR-0537
    vec_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM vec),
    fts_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM fts),
    ng_max   AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM ngram),
    hot_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM hot),
    rec_max  AS (SELECT COALESCE(MAX(raw_score), 0.001) AS hi FROM recency),
    fused AS (
        SELECT id, SUM(contribution) AS fused_score
        FROM (
            SELECT v.id,
                   p_w_vector * (v.raw_score - (-1.0))
                       / GREATEST(b.hi - (-1.0), 0.001) AS contribution
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
    ),
    -- source: ADR-0537
    confidence_weighted AS (
        SELECT tb.id,
               tb.final_score * COALESCE(c.confidence, 1.0) AS final_score
        FROM tag_boosted tb
        JOIN candidates c ON c.id = tb.id
    ),
    -- source: ADR-0537
    trust_weighted AS (
        SELECT cw.id,
               cw.final_score * CASE
                   WHEN c.capture_origin = ANY(p_trusted_origins) THEN 1.0
                   ELSE p_untrusted_factor
               END AS final_score
        FROM confidence_weighted cw
        JOIN candidates c ON c.id = cw.id
    )
    SELECT tw.id,
           c.content,
           tw.final_score::REAL,
           effective_heat(c, NOW(), v_factor)::REAL AS heat,
           c.domain,
           c.created_at,
           c.store_type,
           c.tags,
           c.importance,
           c.surprise_score,
           c.emotional_valence,
           c.source,
           COALESCE(c.value, 0.5)::REAL,
           COALESCE(c.source_attribution, 'unknown')::TEXT,
           COALESCE(c.capture_origin, 'unknown')::TEXT
    FROM trust_weighted tw
    JOIN candidates c ON c.id = tw.id
    -- source: ADR-0537
    ORDER BY (c.superseded_by_id IS NOT NULL), tw.final_score DESC
    LIMIT p_max_results * 3;
END;
$$ LANGUAGE plpgsql STABLE
-- source: ADR-0537
SET plan_cache_mode = 'force_custom_plan'
-- source: ADR-0537
SET pg_trgm.similarity_threshold = '0.1';
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
        -- source: ADR-0537
        SELECT unnest(p_seed_entity_ids) AS eid, 1.0::REAL AS act, 0 AS depth
        UNION ALL
        -- source: ADR-0537
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

# source: ADR-0537

SPREAD_ACTIVATION_MEMORIES_FN = """
DROP FUNCTION IF EXISTS spread_activation_memories(
    TEXT[], REAL, REAL, INT, INT, REAL
);
CREATE OR REPLACE FUNCTION spread_activation_memories(
    p_query_terms      TEXT[],
    p_decay            REAL DEFAULT 0.65,
    p_threshold        REAL DEFAULT 0.1,
    p_max_depth        INT DEFAULT 3,
    p_max_results      INT DEFAULT 50,
    p_min_heat         REAL DEFAULT 0.05,
    p_domain           TEXT DEFAULT NULL,
    p_include_globals  BOOLEAN DEFAULT TRUE
) RETURNS TABLE (
    memory_id   INT,
    activation  REAL
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE
    -- source: ADR-0537
    seed_entities AS (
        SELECT DISTINCT e.id AS eid
        FROM entities e, unnest(p_query_terms) AS t(term)
        WHERE LOWER(e.name) = LOWER(t.term)
          AND e.heat >= p_min_heat
          AND NOT e.archived
    ),
    -- source: ADR-0537
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
    -- source: ADR-0537
    entity_acts AS (
        SELECT s.eid, MAX(s.act)::REAL AS act
        FROM spread s
        JOIN entities e ON e.id = s.eid
        WHERE e.heat >= p_min_heat AND NOT e.archived
        GROUP BY s.eid
    ),
    -- source: ADR-0537
    entity_memories AS (
        SELECT DISTINCT m.id AS mid, ea.act
        FROM entity_acts ea
        JOIN entities e ON e.id = ea.eid
        JOIN current_memories m
            ON m.content_tsv @@ phraseto_tsquery('english', e.name)
        WHERE m.heat_base >= p_min_heat AND NOT m.is_stale
          AND (p_domain IS NULL
               OR m.domain = p_domain
               OR (p_include_globals AND m.is_global = TRUE))
    )
    -- source: ADR-0537
    SELECT em.mid, MAX(em.act)::REAL
    FROM entity_memories em
    GROUP BY em.mid
    ORDER BY MAX(em.act) DESC
    LIMIT p_max_results;
END;
$$ LANGUAGE plpgsql STABLE;
"""

# source: ADR-0537

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
      AND (p_domain IS NULL OR m.domain = p_domain
           OR (p_include_globals AND m.is_global = TRUE))
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
-- source: ADR-0537
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
        ALTER TABLE memories ADD COLUMN heat_base_set_at TIMESTAMPTZ
            NOT NULL DEFAULT NOW();
        UPDATE memories
            SET heat_base_set_at = COALESCE(last_accessed, created_at, NOW());
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'no_decay'
    ) THEN
        ALTER TABLE memories ADD COLUMN no_decay BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    -- source: ADR-0537
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'forgetting_pressure_accum'
    ) THEN
        ALTER TABLE memories
            ADD COLUMN forgetting_pressure_accum REAL NOT NULL DEFAULT 0;
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'uq_relationships_canonical_co_retrieval'
    ) THEN
        -- source: ADR-0537
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

        -- source: ADR-0537
        CREATE UNIQUE INDEX uq_relationships_canonical_co_retrieval
            ON relationships (source_entity_id, target_entity_id, relationship_type)
            WHERE relationship_type = 'co_retrieval';
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'is_benchmark'
    ) THEN
        ALTER TABLE memories ADD COLUMN is_benchmark BOOLEAN DEFAULT FALSE;
    END IF;
END $$;

-- source: ADR-0537
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

-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_memories_not_benchmark
    ON memories (heat_base DESC) WHERE NOT is_benchmark;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'agent_context'
    ) THEN
        ALTER TABLE memories ADD COLUMN agent_context TEXT DEFAULT '';
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'value'
    ) THEN
        ALTER TABLE memories ADD COLUMN value REAL DEFAULT 0.5;
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'source_attribution'
    ) THEN
        ALTER TABLE memories ADD COLUMN source_attribution TEXT DEFAULT 'unknown';
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'capture_origin'
    ) THEN
        ALTER TABLE memories
            ADD COLUMN capture_origin TEXT NOT NULL DEFAULT 'unknown';
        -- source: ADR-0537
        UPDATE memories SET capture_origin = 'legacy';
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'stimulus_signature'
    ) THEN
        ALTER TABLE memories ADD COLUMN stimulus_signature TEXT DEFAULT '';
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'extinction_strength'
    ) THEN
        ALTER TABLE memories ADD COLUMN extinction_strength REAL DEFAULT 0.0;
    END IF;
END $$;

-- source: ADR-0537
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

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'supersedes_id'
    ) THEN
        ALTER TABLE memories ADD COLUMN supersedes_id INTEGER
            REFERENCES memories(id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'superseded_by_id'
    ) THEN
        ALTER TABLE memories ADD COLUMN superseded_by_id INTEGER
            REFERENCES memories(id) ON DELETE SET NULL;
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'stage_entered_at'
    ) THEN
        ALTER TABLE memories ADD COLUMN stage_entered_at TIMESTAMPTZ;
        -- source: ADR-0537
        UPDATE memories SET stage_entered_at = created_at
            WHERE stage_entered_at IS NULL;
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'ingested_at'
    ) THEN
        ALTER TABLE memories ADD COLUMN ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        -- source: ADR-0537
        UPDATE memories SET ingested_at = created_at;
    END IF;
END $$;

-- source: ADR-0537
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='memories' AND column_name='arousal')
    THEN ALTER TABLE memories ADD COLUMN arousal REAL NOT NULL DEFAULT 0.0
        CHECK (arousal >= 0.0 AND arousal <= 1.0);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='memories'
                   AND column_name='dominant_emotion')
    THEN ALTER TABLE memories ADD COLUMN dominant_emotion TEXT
        NOT NULL DEFAULT 'neutral'
        CHECK (dominant_emotion IN ('frustration','satisfaction','confusion',
                                    'urgency','discovery','neutral'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_memories_dominant_emotion
    ON memories (dominant_emotion) WHERE dominant_emotion != 'neutral';

-- source: ADR-0537
CREATE OR REPLACE FUNCTION normalize_domain() RETURNS trigger AS $$
BEGIN
    NEW.domain := LOWER(COALESCE(NEW.domain, ''));
    IF NEW.domain IN ('jarvis', 'cortex-cowork') THEN NEW.domain := 'cortex'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgname = 'trg_memories_domain_normalize') THEN
        CREATE TRIGGER trg_memories_domain_normalize
        BEFORE INSERT OR UPDATE OF domain ON memories
        FOR EACH ROW EXECUTE FUNCTION normalize_domain();
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger
                   WHERE tgname = 'trg_entities_domain_normalize') THEN
        CREATE TRIGGER trg_entities_domain_normalize
        BEFORE INSERT OR UPDATE OF domain ON entities
        FOR EACH ROW EXECUTE FUNCTION normalize_domain();
    END IF;
END $$;

-- source: ADR-0537
CREATE INDEX IF NOT EXISTS idx_entities_lower_name ON entities (LOWER(name));

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes WHERE indexname = 'uq_relationships_directed'
    ) THEN
        DELETE FROM relationships r
        USING (
            SELECT source_entity_id, target_entity_id, relationship_type,
                   MIN(id) AS keep_id
            FROM relationships
            GROUP BY source_entity_id, target_entity_id, relationship_type
            HAVING COUNT(*) > 1
        ) dup
        WHERE r.source_entity_id = dup.source_entity_id
          AND r.target_entity_id = dup.target_entity_id
          AND r.relationship_type = dup.relationship_type
          AND r.id <> dup.keep_id;

        CREATE UNIQUE INDEX uq_relationships_directed
            ON relationships (source_entity_id, target_entity_id, relationship_type);
    END IF;
END $$;

-- source: ADR-0537
CREATE TABLE IF NOT EXISTS ingest_progress (
    run_id text PRIMARY KEY,
    last_key_committed text NOT NULL DEFAULT '',
    rows_committed bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

-- source: ADR-0537
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='prospective_memories'
                   AND column_name='created_by')
    THEN ALTER TABLE prospective_memories ADD COLUMN created_by TEXT
        NOT NULL DEFAULT '';
    END IF;
END $$;

-- source: ADR-0537
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='entities' AND column_name='origin')
    THEN
        ALTER TABLE entities ADD COLUMN origin TEXT NOT NULL DEFAULT 'text_concept'
            CHECK (origin IN ('ast_symbol', 'text_concept'));
        UPDATE entities SET origin = 'ast_symbol'
        WHERE LOWER(type) IN ('function','method','class','struct','module',
                              'file','interface','trait','protocol','enum',
                              'type','constant','variable')
           OR name LIKE '%/%'
           OR (length(name) - length(replace(name, '.', ''))) >= 2;
    END IF;
END $$;

-- source: ADR-0537
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'injection_receipts_channel_enum'
    ) THEN
        ALTER TABLE injection_receipts
            ADD CONSTRAINT injection_receipts_channel_enum CHECK (
                channel IN ('recall', 'session_start', 'auto_recall', 'agent_briefing')
            );
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'wiki' AND table_name = 'pages'
          AND column_name = 'documents_primary'
    ) THEN
        ALTER TABLE wiki.pages ADD COLUMN documents_primary TEXT;
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'page_sources_link_kind_check'
          AND pg_get_constraintdef(oid) NOT LIKE '%finding%'
    ) THEN
        ALTER TABLE wiki.page_sources DROP CONSTRAINT page_sources_link_kind_check;
        ALTER TABLE wiki.page_sources ADD CONSTRAINT page_sources_link_kind_check
            CHECK (link_kind IN ('documents','references','derived','finding'));
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'page_sources_source_check'
          AND pg_get_constraintdef(oid) NOT LIKE '%ap-pipeline%'
    ) THEN
        ALTER TABLE wiki.page_sources DROP CONSTRAINT page_sources_source_check;
        ALTER TABLE wiki.page_sources ADD CONSTRAINT page_sources_source_check
            CHECK (source IN (
              'frontmatter','claim_evidence','body','codebase_grounding','ap-pipeline'
            ));
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'page_sources_link_kind_check'
          AND pg_get_constraintdef(oid) NOT LIKE '%extracted_from%'
    ) THEN
        ALTER TABLE wiki.page_sources DROP CONSTRAINT page_sources_link_kind_check;
        ALTER TABLE wiki.page_sources ADD CONSTRAINT page_sources_link_kind_check
            CHECK (link_kind IN (
              'documents','references','derived','finding','extracted_from'
            ));
    END IF;
END $$;

-- source: ADR-0537
CREATE UNIQUE INDEX IF NOT EXISTS uq_wiki_citations_page_session
    ON wiki.citations (page_id, session_id)
    WHERE session_id <> '';

-- source: ADR-0537
CREATE UNIQUE INDEX IF NOT EXISTS uq_wiki_citations_page_memory
    ON wiki.citations (page_id, memory_id)
    WHERE memory_id IS NOT NULL;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'homeostatic_state' AND column_name = 'write_class'
    ) THEN
        ALTER TABLE homeostatic_state ADD COLUMN write_class TEXT
            NOT NULL DEFAULT 'auto'
            CHECK (write_class IN ('auto', 'deliberate', 'derived', 'mechanical'));
        -- source: ADR-0537
        ALTER TABLE homeostatic_state DROP CONSTRAINT homeostatic_state_pkey;
        ALTER TABLE homeostatic_state ADD PRIMARY KEY (domain, write_class);
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'write_class'
    ) THEN
        ALTER TABLE memories ADD COLUMN write_class TEXT NOT NULL DEFAULT 'deliberate'
            CHECK (write_class IN ('auto', 'deliberate', 'derived', 'mechanical'));
    END IF;
END $$;

-- source: ADR-0537
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memory_rules' AND column_name = 'source_memory_id'
    ) THEN
        ALTER TABLE memory_rules ADD COLUMN source_memory_id INTEGER;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'prospective_memories' AND column_name = 'source_memory_id'
    ) THEN
        ALTER TABLE prospective_memories ADD COLUMN source_memory_id INTEGER;
    END IF;
END $$;

-- source: ADR-0537
ALTER TABLE wiki.pages DROP CONSTRAINT IF EXISTS pages_status_check;
ALTER TABLE wiki.pages ADD CONSTRAINT pages_status_check CHECK (
    status IN (
      'seedling','budding','evergreen','living',
      'proposed','accepted','rejected','deprecated','superseded',
      'draft','review','implemented'
    )
);
"""

# ── Schema initialization ────────────────────────────────────────────────


def _strip_sql_line_comments(ddl: str) -> str:
    """Remove ``--`` line comments before statement splitting.

    A ``--`` begins a comment only outside a single-quoted string literal;
    everything from it to end-of-line is dropped. Without this, a semicolon
    *inside* a comment (e.g. ``-- ...participate in a version chain; on a store
    with no edges these are empty and cost nothing.``) is mistaken for a
    statement terminator by the ``;``-splitter, and the comment tail after the
    semicolon is then executed as SQL — a syntax error on schema init.
    """
    cleaned = []
    for line in ddl.splitlines():
        in_str = False
        cut = len(line)
        idx = 0
        while idx < len(line):
            ch = line[idx]
            if ch == "'":
                in_str = not in_str
            elif (
                ch == "-"
                and not in_str
                and idx + 1 < len(line)
                and line[idx + 1] == "-"
            ):
                cut = idx
                break
            idx += 1
        cleaned.append(line[:cut].rstrip())
    return "\n".join(cleaned)


def _split_statements(ddl: str) -> list[str]:
    """Split a multi-statement DDL string into individual statements.

    Handles CREATE FUNCTION blocks that contain semicolons in the
    body by detecting $$ delimiters.
    """
    if "$$" in ddl:
        # PL/pgSQL function — return as single block
        return [ddl.strip()] if ddl.strip() else []
    statements = []
    for part in _strip_sql_line_comments(ddl).split(";"):
        # source: ADR-0537
        lines = [ln for ln in part.splitlines()]
        # remove leading blank/comment lines
        while lines and (not lines[0].strip() or lines[0].lstrip().startswith("--")):
            lines.pop(0)
        stmt = "\n".join(lines).strip()
        if stmt:
            statements.append(stmt + ";")
    return statements


def get_all_ddl() -> list[LiteralString]:
    """Return all DDL as individual statements for safe per-statement execution.

    source: ADR-0537"""
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
        PROCEDURAL_SKILLS_DDL,
        # source: ADR-0537
        MIGRATIONS_DDL,
        MEMORIES_STORAGE_OPTIONS_DDL,
        # source: ADR-0537
        CURRENT_MEMORIES_VIEW_DDL,
        INDEXES_DDL,
        # source: ADR-0537
        EFFECTIVE_STAGE_FN,
        ALPHA_INTEGRAL_FN,
        EFFECTIVE_HEAT_FN,
        EFFECTIVE_HEAT_FROZEN_FN,
        # source: ADR-0537
        RECALL_MEMORIES_LAZY_FN,
        SPREAD_ACTIVATION_FN,
        SPREAD_ACTIVATION_MEMORIES_FN,
        GET_HOT_EMBEDDINGS_FN,
        GET_TEMPORAL_CO_ACCESS_FN,
    ]
    result: list[str] = []
    for block in blocks:
        result.extend(_split_statements(block))
    # source: ADR-0537
    return cast("list[LiteralString]", result)
