"""PostgreSQL schema: DDL, extensions, stored procedures, migrations.

Requires PostgreSQL 15+ with pgvector and pg_trgm extensions.
All retrieval logic lives in PL/pgSQL stored procedures.

Pure DDL — no connection management.
"""

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
    -- M-D2 (7.4, 2026-07-11): explicit write class, the single contract
    -- mcp_server/core/write_class.py classifies against. DEFAULT
    -- 'deliberate' is the module's documented safe default (an
    -- unclassified write is never assumed to be flood/noise) — fresh
    -- installs get every writer's EXPLICIT value at insert time
    -- (handlers/remember.py, ingest_findings_writers.py, cls.py,
    -- sleep.py, etc.; see write_class.py module docstring for the full
    -- writer inventory), so this DEFAULT only matters for the historical
    -- backfill window on pre-existing installs (MIGRATIONS_DDL below +
    -- the one-shot handlers/consolidation/write_class_backfill.py pass).
    write_class     TEXT NOT NULL DEFAULT 'deliberate'
                    CHECK (write_class IN
                        ('auto', 'deliberate', 'derived', 'mechanical'))
);
"""

# Supersession read-path layer (PR "read-path supersession"). The invariant
# "chain head = current version" is defined exactly ONCE, here: a row is
# current iff nothing has superseded it (superseded_by_id IS NULL,
# stamped atomically by supersede_atomic). Every content-serving read
# selects FROM current_memories; physical maintenance (decay/forgetting
# cursors), chain machinery (_current_chain_head, include_related) and
# explicit by-id reads stay on memories by contract. Coverage audit:
# grep current_memories. Audit + spec:
# docs/program/pr2-read-path-supersession-audit.json.
# CREATE OR REPLACE is idempotent; executed AFTER MIGRATIONS_DDL in
# get_all_ddl() so databases predating the supersession columns gain
# them first. The planner inlines this single-predicate view, and the
# predicate is benchmark-neutral by construction (fixtures never set
# superseded_by_id, so view ≡ table on all benchmark data).
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
    -- Provenance: 'ast_symbol' (code symbol from codebase ingestion — exempt
    -- from label-fuzzy dedup, graphify #1205) vs 'text_concept' (extracted from
    -- memory content — eligible for fuzzy dedup). Consumed by core.entity_dedup.
    origin          TEXT NOT NULL DEFAULT 'text_concept'
                    CHECK (origin IN ('ast_symbol', 'text_concept'))
);
"""

HOMEOSTATIC_STATE_DDL = """
-- M-D3 (7.1, 2026-07-10): one row per (domain, write_class), not one row
-- per domain. The pre-stratification single-row-per-domain fold regulated
-- every write class toward the same target mean using the same factor —
-- confirmed (SQL, dev DB) to have re-suppressed the deliberate class in
-- the SAME UPDATE as the auto-capture flood at 2026-07-10 19:22 (1021
-- rows folded together, 511 post_tool_capture + 510 deliberate-class
-- sources, domain=''). See mcp_server/core/write_class.py for the
-- taxonomy and mcp_server/handlers/consolidation/homeostatic.py for the
-- per-class regulation policy. Fresh installs get the composite key
-- directly; existing installs are migrated by the DO block below
-- (MIGRATIONS_DDL) which backfills write_class='auto' via column DEFAULT
-- — the honest one-shot label for legacy rows, since their factor
-- history was driven by a corpus that was 92% auto-capture by volume.
CREATE TABLE IF NOT EXISTS homeostatic_state (
    domain      TEXT NOT NULL,
    write_class TEXT NOT NULL DEFAULT 'auto'
                CHECK (write_class IN ('auto', 'deliberate', 'derived', 'mechanical')),
    factor      REAL NOT NULL DEFAULT 1.0
                CHECK (factor > 0.0 AND factor < 10.0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain, write_class)
);

-- M-D3 (7.1): fold-event journal — instrumentation the design doc's
-- acceptance criterion required BEFORE any fold-policy change ("pas de
-- correctif sans confirmation du coupable"). The 2026-07-10 19:22 fold
-- left no queryable trace anywhere except memories.heat_base_set_at
-- matching a batched write — every fold from this point forward is
-- queryable directly, no row-timestamp archaeology required.
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
    confidence      REAL NOT NULL DEFAULT 0.5
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
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
    -- Denormalized 1:1 fast-path mirror of wiki.page_sources for the
    -- dominant single-file-doc case: keeps the recall hot path join-free
    -- (see "ZERO joins from recall hot path" invariant above). NULL for
    -- pages that document zero or many files; wiki.page_sources is the
    -- source of truth for the N:M case. ADR-0051.
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
    -- Union of the digital-garden maturity vocabulary (seedling/budding/
    -- evergreen, the column default) with every status vocabulary the
    -- system itself emits into frontmatter: 'living' (core/auto_curator.py
    -- lines 475,538 and handlers/consolidation/page_io.py:376) and the
    -- kind-specific ADR/specs statuses in
    -- core/wiki_templates.py STATUS_VALUES (proposed/accepted/rejected/
    -- deprecated/superseded for ADRs; draft/review/accepted/implemented/
    -- deprecated for specs). Kept in sync manually with wiki_migrate.py's
    -- _VALID_STATUS_VALUES (handlers may import core; infrastructure may
    -- not, so the union is duplicated here with this provenance comment
    -- rather than imported).
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

-- page_sources: N:M edge from a wiki page to the source file(s) it
-- documents. General model — an anchor/scope page can document many
-- files, and (rarely) a file can be documented by more than one page
-- (e.g. a module overview plus a deep-dive). Populated from frontmatter
-- (`documents:`/legacy `source_file_path`/`file`/`file:` tag) and from
-- wiki.claim_events.evidence_refs (kind='file'). Mirrors wiki.links'
-- shape (src table row -> target key, typed by link_kind).
-- Downstream consumer: cortex-viz wiki-page -> source-file edges.
-- ADR-0051.
CREATE TABLE IF NOT EXISTS wiki.page_sources (
    page_id         INTEGER NOT NULL REFERENCES wiki.pages(id) ON DELETE CASCADE,
    source_path     TEXT NOT NULL,
    symbol          TEXT,
    link_kind       TEXT NOT NULL DEFAULT 'documents'
                    -- 'finding' added INC5.1 (ADR-0052 D4): AP-finding ->
                    -- file-reference edges written by ingest_findings
                    -- (code files the finding is ABOUT, stage-4
                    -- matched_symbols). 'extracted_from' added 5.1b:
                    -- AP-finding -> source-document edge (stage-1
                    -- ExtractedFinding.source_path — the document the
                    -- finding was extracted FROM). Kept distinct from
                    -- 'finding' so a graph reader can tell provenance
                    -- apart from subject matter.
                    CHECK (link_kind IN (
                      'documents','references','derived','finding','extracted_from'
                    )),
    confidence      REAL NOT NULL DEFAULT 1.0,
    source          TEXT NOT NULL DEFAULT 'frontmatter'
                    -- 'ap-pipeline' added INC5.1: provenance tag for rows
                    -- written by ingest_findings from AP artifacts.
                    CHECK (source IN (
                      'frontmatter','claim_evidence','body','codebase_grounding',
                      'ap-pipeline'
                    )),
    PRIMARY KEY (page_id, source_path, link_kind)
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
-- pgvector default changes. source: docs/provenance/hnsw-determinism-playbook.md §1
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

-- Reverse index: file -> page(s) documenting it. The query the viz
-- edge-builder actually runs.
CREATE INDEX IF NOT EXISTS idx_wiki_page_sources_path
    ON wiki.page_sources (source_path);

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
--
-- The +0.05 bump has NO published or measured source (coding-standards.md
-- §8 gap, flagged twice: design inc5 risk D7, report T2-H4). It is an
-- unvalidated engineering default, introduced at the trigger's origin
-- (commit 4516b489, "feat(wiki redesign): Phase 1.1") with no derivation
-- beyond "same physics as pg_store memory decay" (wiki_thermodynamics.py
-- module docstring). It is internally consistent with two other
-- single-reinforcement-event heat bumps in this codebase that are
-- likewise unsourced engineering defaults of the same magnitude:
--   - mcp_server/core/reconsolidation.py:310 _RECONS_HEAT_BUMP_UPDATE = 0.05
--     (memories.heat bump on retrieval-driven reconsolidation update;
--     explicitly labelled "calibration pending" in that module)
--   - mcp_server/infrastructure/pg_store_relationships.py:181
--     entities.heat bump on Hebbian co-activation, also +0.05, also
--     unsourced.
-- No empirical calibration is possible yet either: wiki.citations has 0
-- rows in the dev DB as of 2026-07-10 (feature not yet exercised in
-- practice), and all 154 existing wiki.pages sit at heat 0.95-1.0
-- (cap-saturated at LEAST(1.0, ...)), so the bump has had zero observable
-- effect to date and no distribution exists to calibrate against.
-- Structural implication of the current value (informational, not a
-- justification): with the 1.0 cap and the 0.4 ARCHIVED_REVIVAL_HEAT
-- threshold (wiki_thermodynamics.py), a single citation cannot revive an
-- archived page (heat near AREA_TO_ARCHIVED_HEAT=0.1 floor) on its own —
-- reaching 0.4 needs >=6 citations with no intervening decay.
-- source: none — engineering default, calibration pending. See
-- docs/provenance/ (blend-weight-calibration.md precedent for how this
-- codebase resolves "engineering default" placeholders: pre-register a
-- sweep, cite the resulting optimum, update this comment).
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
    -- M-D6 (7.6): the lesson memory this trigger was promoted from, when
    -- created via a lesson_promotion job (mcp_server/handlers/
    -- lesson_promotion.py). NULL for triggers created directly by
    -- create_trigger without going through a promotion job. No FK: same
    -- unenforced-pointer convention as memories' `derived-src:<id>` tags
    -- (memify_derive.py) — a hard-forgotten source lesson must not force
    -- deletion of the trigger it produced.
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

-- Injection receipts (blame path T1/T2 — decision Cortex 4255039). Every
-- channel that injects memory content into a context emits, at injection
-- time, an append-only receipt capturing {memory_id, rank, score} for
-- exactly the bound payload (emitted AFTER bound_payload: transcript↔DB
-- parity invariant). Presence-in-context evidence only, never causality
-- (Pearl ladder). session_id is NULLable: the mcp recall handler has no
-- session identity in scope; hook channels derive it from the transcript
-- file basename (correction 7). channel is enum-hardened (T2): the four
-- values mirror handlers/injection_receipts.py INJECTION_CHANNELS —
-- parity asserted by test_injection_receipts_store.py.
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

-- memory_id carries NO FK on purpose: receipts are an append-only audit
-- trail — a later hard-forget of the memory must not rewrite the evidence
-- of what was in context (unlike stage_transitions, whose rows lose all
-- value once the memory is gone).
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
    -- M-D6 (7.6): the lesson memory this rule was promoted from, when
    -- created via a lesson_promotion job. NULL for rules created
    -- directly by add_rule without going through a promotion job.
    -- READ-PATH NOTE: memory_rules is read every recall via
    -- core.memory_rules.apply_rules (SELECT * in get_all_active_rules /
    -- get_rules_for_scope, so this column is included automatically).
    -- apply_rules() only ever reads rule_type/condition/action/priority
    -- — it does not reference source_memory_id — so this addition does
    -- NOT change recall's filtering or ranking decision, only the
    -- shape of rows it already reads. No FK: same unenforced-pointer
    -- convention as memories' `derived-src:<id>` tags.
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

-- User session-level mood state for MOOD_CONGRUENT_RERANK (Bower 1981).
-- Single-row table keyed by user_id (default 'default') so the recall
-- pipeline's _get_user_mood(store) bridge can read a real signal instead
-- of always returning None. The seed row defaults to neutral (valence=0,
-- arousal=0) — consumers may update via set_user_mood() once an upstream
-- emotion classifier wires in. The duck-typed pg_recall._get_user_mood()
-- bridge consumes the scalar `valence` only. `arousal` is reserved for the
-- two-dimensional Russell (1980) circumplex if a future stage needs it.
-- Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
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

-- Precomputed (x, y) coordinates for every workflow-graph node. The
-- layout pass runs out-of-band (handlers/recompute_layout.py via
-- igraph DrL on CPU) and persists the result here so the viz can ship
-- coordinates with each node, eliminating the d3-force tick cost in
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

# ── Procedural memory (B1) ────────────────────────────────────────────────
# Skills = recurring successful action sequences mined from session tool-use
# (Graybiel 2008 chunking) with a reinforced success rate (Schultz 1997 RPE).
# Retrieved by *situation* (context_signature), never by content similarity —
# the defining split from the declarative episodic/semantic store. A dedicated
# table (mirroring prospective_memories) rather than a memories.store_type row,
# because a skill's fields (ordered action sequence, proficiency, success/
# failure counts) are structured, not free text. Idempotent, additive: this
# CREATE IF NOT EXISTS touches no existing table.
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
-- Composite key for KEYSET pagination of the viz graph build
-- (iter_hot_memories_chunked): ``ORDER BY heat_base DESC, id DESC`` with a
-- ``(heat_base, id) < (...)`` cursor becomes a pure index range scan, no
-- per-page sort even across the large heat_base tie groups (e.g. 149k rows
-- at one heat value). source: EXPLAIN, 2026-06-03.
CREATE INDEX IF NOT EXISTS idx_memories_heat_base_id
    ON memories (heat_base DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_memories_domain
    ON memories (domain);
-- M-D2 (7.4): the homeostatic fold's UPDATE (homeostatic_apply.py::
-- _apply_fold) filters WHERE domain = %s AND write_class = %s — this
-- composite index makes that an index range scan instead of a domain-
-- only scan + per-row filter.
CREATE INDEX IF NOT EXISTS idx_memories_domain_write_class
    ON memories (domain, write_class);
CREATE INDEX IF NOT EXISTS idx_memories_store_type
    ON memories (store_type);
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories (created_at);
CREATE INDEX IF NOT EXISTS idx_memories_stage
    ON memories (consolidation_stage);
-- Grooming telemetry (get_grooming_health): candidate/backlog counts filter
-- on tags @> '["lesson"]'::jsonb / tag-prefix scans ('promoted:%',
-- 'distill-of:%'). Without this index the same query the promotion
-- planner already runs (pg_store_lesson_promotion.list_lesson_promotion_
-- candidates) is a full Seq Scan over `memories` (measured: 81ms at
-- 11,012 rows, EXPLAIN ANALYZE 2026-07-11 -- grows linearly with table
-- size). Mirrors the existing idx_wiki_pages_tags_gin index already
-- proven on wiki.pages.tags (pg_schema.py:431).
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
-- Supersession chain walks (borrow-from-supermemory item 1). Partial so the
-- index covers only the sparse subset of memories that participate in a
-- version chain; on a store with no edges these are empty and cost nothing.
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

EFFECTIVE_STAGE_FN = """
-- effective_stage — LAZY read-time derivation of the consolidation stage.
--
-- Root cause (memory 4202985): A3 made HEAT lazy (decayed from stage_hours
-- on the read path) but left STAGE eager — advanced only by the
-- consolidation handler (handlers/consolidation/cascade.py), never on
-- recall/read. Benchmark and import runs trigger no consolidation pass, so
-- a row stays frozen at its insert stage 'labile' (α=2.0, floor=0.0) while
-- its heat decays under the labile law → collapses to ~0. This function
-- re-derives the stage lazily from elapsed dwell + the row's stored signal
-- columns so α and the floor track the trace's true maturity.
--
-- Mirrors cascade_advancement.compute_advancement_readiness applied
-- cumulatively (advance as far as time + signals permit, one shot),
-- forward-chain only (labile→early_ltp→late_ltp→consolidated), monotonic
-- (never demote below the stored stage). The DA gate of the LABILE→EARLY_LTP
-- transition is encoding-time and unavailable on the read path, so only the
-- importance gate is used (dopamine treated as absent).
--
-- stage_hours is treated as a dwell BUDGET consumed stage-by-stage: leaving
-- a stage requires budget ≥ that stage's effective min_dwell, and consumes it.
--
-- min_dwell hours: labile=0, early_ltp=1, late_ltp=6, consolidated=24.
--   source: cascade_stages._STAGE_PROPERTIES (Kandel 2001)
-- schema acceleration on min_dwell (cascade_advancement._effective_min_dwell):
--   systems-consolidation stages (late_ltp, consolidated): × 15^(-schema)
--     (Tse 2007 ~10-15× acceleration; 15.0 base is an engineering choice)
--   synaptic-tag stages (labile, early_ltp): × (1 - schema·0.2)
-- signal gates (cascade_advancement._check_*_advancement):
--   labile→early_ltp:     importance > 0.3            (DA path disabled at read)
--   early_ltp→late_ltp:   access_count ≥ 1 OR importance > 0.4
--   late_ltp→consolidated: access_count ≥ (3 if schema < 0.5 else 1)
-- 'reconsolidating' and any unknown stage are returned unchanged — they are
-- access-triggered (Nader 2000), not time-derivable.
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
    -- Only the forward synaptic-tag chain is derived lazily.
    IF cur NOT IN ('labile', 'early_ltp', 'late_ltp', 'consolidated') THEN
        RETURN cur;
    END IF;

    -- LABILE → EARLY_LTP. min_dwell(labile)=0 → no budget consumed.
    IF cur = 'labile' THEN
        IF imp > 0.3 THEN
            cur := 'early_ltp';
        ELSE
            RETURN cur;
        END IF;
    END IF;

    -- EARLY_LTP → LATE_LTP. effective min_dwell = 1.0 · (1 - schema·0.2).
    IF cur = 'early_ltp' THEN
        dwell := 1.0 * (1.0 - sch * 0.2);
        IF budget >= dwell AND (acc >= 1 OR imp > 0.4) THEN
            budget := budget - dwell;
            cur := 'late_ltp';
        ELSE
            RETURN cur;
        END IF;
    END IF;

    -- LATE_LTP → CONSOLIDATED. effective min_dwell = 6.0 · 15^(-schema).
    IF cur = 'late_ltp' THEN
        dwell := 6.0 * POWER(15.0, -sch);
        late_thr := CASE WHEN sch < 0.5 THEN 3 ELSE 1 END;
        IF budget >= dwell AND acc >= late_thr THEN
            cur := 'consolidated';
        END IF;
    END IF;

    -- CONSOLIDATED is terminal on the forward chain.
    RETURN cur;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
"""

ALPHA_INTEGRAL_FN = """
-- alpha_integral — cumulative α-weighted dwell time ∫₀^τ α(stage(s)) ds.
--
-- Root cause (forgetting-curve fidelity benchmark, 2026-06-30): effective_heat
-- applied α(final stage) to ALL elapsed hours. When a trace matures, α drops
-- (late_ltp 0.8 → consolidated 0.5); applying the lower α retroactively to the
-- whole past made the decay exponent α·t DECREASE across a stage boundary, so
-- heat ROSE with age — non-physical, non-monotonic forgetting (e.g.
-- B_consolidated 6h heat 0.98982 → 8h 0.99151).
--
-- Fix: the instantaneous decay rate is α(stage at dwell-time s). The decay
-- accumulated over a window is the INTEGRAL of α over that window, not
-- α(endpoint)·window. This returns ∫₀^p_tau α(stage(s)) ds on the dwell clock,
-- walking the SAME forward chain as effective_stage() (identical gates and
-- effective min_dwell). α>0 everywhere ⇒ the integral is strictly increasing
-- in p_tau ⇒ POWER(p_factor, integral) is monotone decreasing ⇒ forgetting is
-- monotone by construction.
--
-- α(stage): labile=2.0, early_ltp=1.2, late_ltp=0.8, consolidated=0.5,
--   reconsolidating=1.5, other=1.0. source: pg_schema effective_heat α ladder
--   (Kandel 2001 stage-dependent decay exponent).
-- Stage durations mirror effective_stage: labile min_dwell 0 (imp>0.3 gate,
--   instant); early_ltp 1.0·(1-0.2·schema) gated on acc≥1 OR imp>0.4; late_ltp
--   6.0·15^(-schema) gated on acc≥(3 if schema<0.5 else 1). A failed gate
--   freezes the trace in that stage for the remaining τ (its α covers the tail).
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
    -- Off-chain stages decay at their fixed α for the whole window.
    IF cur NOT IN ('labile', 'early_ltp', 'late_ltp', 'consolidated') THEN
        RETURN (CASE cur WHEN 'reconsolidating' THEN 1.5 ELSE 1.0 END)
               * remaining;
    END IF;

    -- LABILE: min_dwell 0. imp>0.3 ⇒ leave instantly (0 duration, no α
    -- contribution). Else frozen labile ⇒ α=2.0 for the whole window.
    IF cur = 'labile' THEN
        IF imp > 0.3 THEN
            cur := 'early_ltp';
        ELSE
            RETURN total + 2.0 * remaining;
        END IF;
    END IF;

    -- EARLY_LTP: α=1.2. Leaves after dwell = 1.0·(1-0.2·schema) iff gated.
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

    -- LATE_LTP: α=0.8. Leaves after dwell = 6.0·15^(-schema) iff gated.
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

    -- CONSOLIDATED: terminal, α=0.5 for all remaining τ.
    RETURN total + 0.5 * remaining;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
"""

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
    beta           DOUBLE PRECISION;
    stage_floor    DOUBLE PRECISION;
    base_scaled    DOUBLE PRECISION;
    decayed        DOUBLE PRECISION;
    eff_decay_hours DOUBLE PRECISION;
    eff_stage      TEXT;
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

    -- Lazily derive the effective consolidation stage. A3 made HEAT lazy but
    -- left STAGE eager (advanced only by the consolidation handler, never on
    -- the read path), so between consolidation passes a row's heat decayed
    -- under the labile α while the trace had already earned a later,
    -- slower-decaying stage. effective_stage() re-derives the stage from
    -- elapsed dwell (stage_hours) + the stored signal columns so α and the
    -- floor below match the trace's true maturity, monotonically (never
    -- below the stored stage). 'reconsolidating'/unknown stages pass through
    -- unchanged. source: effective_stage() + cascade_advancement gates.
    eff_stage := effective_stage(
        m.consolidation_stage,
        stage_hours,
        m.importance,
        m.access_count,
        m.schema_match_score
    );

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
    -- Uses the lazily-derived eff_stage (see above) so a trace that has
    -- matured into late_ltp/consolidated gets its retention floor even
    -- between consolidation passes. source: pg_schema.py:742-747
    stage_floor := CASE eff_stage
        WHEN 'consolidated'    THEN 0.10
        WHEN 'late_ltp'        THEN 0.05
        WHEN 'reconsolidating' THEN 0.05
        ELSE 0.0
    END;

    -- Decay exponent = ∫ α(stage(s)) ds over the elapsed window, NOT
    -- α(final stage)·hours_elapsed. The latter applied a matured trace's
    -- lower α retroactively to its whole past, so the exponent could shrink
    -- across a stage boundary and heat ROSE with age (non-monotonic — see
    -- alpha_integral). The decay window on the dwell clock is
    -- [stage_hours - hours_elapsed, stage_hours]; its α-integral is the
    -- difference of cumulative integrals (GREATEST clamps the lower bound for
    -- rows whose heat was last touched before the current stored stage). For a
    -- single-stage trace α is constant ⇒ the difference is exactly
    -- α·hours_elapsed, so single-stage trajectories are byte-identical to the
    -- prior formula; only multi-stage traces change, and only to remove the
    -- non-physical bump. source: alpha_integral() (Kandel 2001).
    eff_decay_hours :=
        alpha_integral(m.consolidation_stage, stage_hours,
                       m.importance, m.access_count, m.schema_match_score)
        - alpha_integral(m.consolidation_stage,
                         GREATEST(0.0, stage_hours - hours_elapsed),
                         m.importance, m.access_count, m.schema_match_score);

    -- Scale base by homeostatic factor (Feynman first-principles: factor
    -- is a scalar-per-domain gain, not a per-row mutation). Then apply the
    -- integrated decay: POWER(p_factor, β · ∫α). β (emotional damping) scales
    -- the whole exponent as a slowly-varying global factor.
    --
    -- All intermediates are DOUBLE PRECISION (float8) to avoid REAL
    -- underflow at ~1e-38. The clamp below pins output ≥ stage_floor,
    -- and the final cast to REAL on RETURN lands in a safe range
    -- because POWER values < 1e-38 collapse to 0 before the cast,
    -- and GREATEST(stage_floor, 0) lifts the value back to stage_floor.
    base_scaled := m.heat_base::DOUBLE PRECISION * factor::DOUBLE PRECISION;
    decayed := base_scaled * POWER(p_factor::DOUBLE PRECISION,
                                   beta * eff_decay_hours);

    -- I1 + I8: clamp to REAL-safe range BEFORE cast. REAL (float4)
    -- cannot represent values below ~1.2e-38 even as sub-normals —
    -- the cast raises NumericValueOutOfRange. stage_floor may be 0
    -- (labile), so use 1e-38 as the hard floor; downstream score
    -- fusion (TMM, Bruch 2023) treats 1e-38 as functionally zero.
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
    p_include_globals BOOLEAN DEFAULT TRUE,
    -- issue #368. Both default to the identity transform: an empty trusted
    -- set with factor 1.0 multiplies every row by 1.0, so a caller that
    -- passes neither reproduces the pre-#368 ranking bit for bit. The set is
    -- supplied by the caller rather than defaulted to a literal vocabulary
    -- here, so this function never holds a copy of the trust policy.
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
    -- issue #368: returned so the read path can break the heat feedback loop
    -- without a second query. Distinct from source_attribution, which is
    -- derived BY READING the content and therefore cannot carry trust.
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
    -- Resolve the homeostatic factor for this domain (1.0 default).
    -- M-D3 (7.1): homeostatic_state's PK is (domain, write_class) since
    -- the fold/scalar regulator was stratified per write class — 'auto'
    -- is the only class ever regulated (see homeostatic.py doctrine
    -- comment), so it is the only class whose factor departs from the
    -- neutral 1.0 default; pinning the filter here reproduces the
    -- pre-stratification recall behavior exactly (same numeric factor
    -- for the same corpus) while remaining correct once other classes'
    -- rows exist in the table.
    SELECT COALESCE(MAX(hs.factor), 1.0) INTO v_factor
    FROM homeostatic_state hs
    WHERE hs.domain = COALESCE(p_domain, '') AND hs.write_class = 'auto';

    -- Prefilter threshold: heat_base >= p_min_heat / factor is the
    -- monotonic transform that preserves ordering (Zhuangzi: positive
    -- factor preserves the order relation on heat_base). Index usable.
    v_min_heat_base := p_min_heat / GREATEST(v_factor, 0.001);

    RETURN QUERY
    WITH
    -- Prefilter: narrow memories by cheap heat_base threshold + stale/
    -- domain/directory gates. All downstream CTEs read `candidates` not
    -- `memories` — that's where the score-fusion (TMM) signal-processing happens.
    -- Reads current_memories (chain heads only): superseded versions are
    -- excluded at the source, so every downstream pool, the TMM fusion and
    -- all client-side re-sorts (RRF, FlashRank, rules, strategic ordering)
    -- are supersession-safe by construction. The tier-sort in the final
    -- ORDER BY is kept verbatim as a constant-true belt-and-braces.
    candidates AS (
        SELECT m.*
        FROM current_memories m
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
    -- Auto-captures are excluded from the heat and recency pools
    -- (bounded-io Phase 2 F2, docs/provenance/bounded-io-phase2-design.md M2):
    -- their freshness is a mechanical artifact of one-write-per-tool-call
    -- (baseline_heat 1.0 + always-recent created_at), carrying no
    -- importance information. Including them let a fresh raw dump join
    -- 4-5 fusion signal pools while month-old curated lessons joined 1-2 — the
    -- measured 60x inversion. Categorical de-bias, no tuned constant;
    -- auto-captures still compete on content (vector/fts/ngram).
    -- Benchmark-neutral: fixtures never write source='post_tool_capture'.
    hot AS (
        SELECT c.id,
               effective_heat(c, NOW(), v_factor) AS raw_score
        FROM candidates c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
          AND c.source <> 'post_tool_capture'
        ORDER BY effective_heat(c, NOW(), v_factor) DESC
        LIMIT v_pool
    ),
    -- Signal 5: Recency via exponential decay
    recency AS (
        SELECT c.id,
               EXP(-0.01 * EXTRACT(EPOCH FROM (NOW() - c.created_at))
                   / 86400.0)::REAL AS raw_score
        FROM candidates c
        WHERE effective_heat(c, NOW(), v_factor) >= p_min_heat
          AND c.source <> 'post_tool_capture'
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
    -- Metamemory confidence as a multiplicative document prior
    -- (Kraaij, Westerveld & Hiemstra 2002, "The Importance of Prior
    -- Probabilities for Entry Page Search", SIGIR — static document
    -- priors multiply the query likelihood). confidence defaults to 1.0
    -- (multiplicative identity) and moves ONLY via rate_memory feedback,
    -- so the prior is data-driven, no invented constant, and an identity
    -- transform on benchmark fixtures. Closes the M3 structural gap
    -- (docs/provenance/bounded-io-phase2-design.md): user feedback previously had
    -- no channel into rank.
    confidence_weighted AS (
        SELECT tb.id,
               tb.final_score * COALESCE(c.confidence, 1.0) AS final_score
        FROM tag_boosted tb
        JOIN candidates c ON c.id = tb.id
    ),
    -- Trust/provenance demotion (issue #368). Source: arXiv 2604.16548 —
    -- retrieve-phase corruption ("malicious entries ranked highest by
    -- embedding similarity"), whose required defence is a trust-aware
    -- retrieval POLICY, the survey being explicit that "Retrieval-time
    -- filtering alone is insufficient". Hence a factor inside the ranking
    -- expression, evaluated before ORDER BY and before the LIMIT, rather
    -- than a filter over an already-ranked list.
    --
    -- Multiplicative like its three predecessors, and necessarily so: an
    -- additive term cannot demote — it contributes at best zero and leaves
    -- a hostile passage's similarity intact.
    --
    -- This function holds NO trust policy of its own. The trusted set
    -- arrives as a parameter so mcp_server/core/capture_origin.py stays the
    -- single source of truth; hardcoding the vocabulary here would let the
    -- two drift apart silently, which is the failure mode the module was
    -- written against. Defaults are the identity transform (empty set,
    -- factor 1.0), so a caller that passes neither gets the pre-#368
    -- ranking exactly.
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
    -- Supersession head-of-chain demotion (borrow-from-supermemory item 1):
    -- a memory that has been superseded (superseded_by_id IS NOT NULL) ranks
    -- below every current version, then by fused score within each tier.
    -- Boolean sorts FALSE < TRUE, so current (NULL -> FALSE) leads. This is a
    -- tier sort, not a tuned penalty -- no invented constant. Benchmark-neutral:
    -- fixtures never set the edge, so the first key is constant FALSE and the
    -- order collapses to the prior ORDER BY cw.final_score DESC.
    ORDER BY (c.superseded_by_id IS NOT NULL), tw.final_score DESC
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
#
# Domain scoping (ADR-0054, 2026-07-11): the entity graph (entities,
# relationships) is intentionally global -- a token shared across projects
# (e.g. "TypeError", "src/main.rs") legitimately creates one shared entity
# row, and relationships carry no domain column by design (see
# RELATIONSHIPS_DDL). Filtering seed_entities or spread by domain would
# starve that legitimate sharing. The injection point that matters is the
# LAST step -- entity_memories, where activation is mapped onto actual
# memory rows -- mirroring the precedent already established by
# pg_recall.py::_memories_by_entity_fn (`if domain and m.get("domain") !=
# domain: continue`) and by recall_memories()'s own p_domain/p_include_globals
# gate on the same `m.domain` column (see RECALL_MEMORIES_LAZY_FN above).
# Measured without this filter (scratchpad/spread-activation-scoping-design.md
# §2.3): 52.8% of topologically-reachable injections are cross-domain,
# 87.5% of queries have >=1 cross-domain hit. p_domain defaults to NULL
# (no filter) only for the two callers that explicitly opt in via
# cross_domain=True (recall_pipeline.py::spreading_activation_expand);
# the default at every layer above this function is scoped.
#
# WITH RECURSIVE fix (bug present since the function's introduction,
# 8228a0d2): the `spread` CTE self-references (`FROM spread s`) but the
# original declaration used a plain `WITH`, which PostgreSQL rejects
# ("relation \"spread\" does not exist") on every single call -- the
# entire channel has been dead in production since inception, its
# exception silently swallowed by recall_pipeline.py's `except Exception:
# return candidates`. See spread_activation() above, which already used
# WITH RECURSIVE correctly -- this was the only divergence between the
# two twin functions.

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
    -- Step 1: Resolve query terms to entity IDs (case-insensitive)
    seed_entities AS (
        SELECT DISTINCT e.id AS eid
        FROM entities e, unnest(p_query_terms) AS t(term)
        WHERE LOWER(e.name) = LOWER(t.term)
          AND e.heat >= p_min_heat
          AND NOT e.archived
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
    -- Step 3: Map entity activations to memories via FTS + ILIKE.
    -- current_memories: spread activation re-injects candidates from the
    -- entity graph AFTER the WRRF ranking — a superseded version reached
    -- through its entities would bypass every ranking barrier, so chain
    -- heads only. Domain filter here (not on entities/relationships,
    -- see module comment above) mirrors recall_memories()'s p_domain/
    -- p_include_globals gate on the same m.domain column.
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
    -- A2 active forgetting: leaky-integrator state for the permanent (Rac1)
    -- circuit. Accumulates chronic-interference pressure across consolidation
    -- cycles; sustained pressure (accum >= Theta_accum) marks the trace stale.
    -- source: mcp_server/core/active_forgetting.py (update_pressure_accum).
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'forgetting_pressure_accum'
    ) THEN
        ALTER TABLE memories
            ADD COLUMN forgetting_pressure_accum REAL NOT NULL DEFAULT 0;
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

-- Migration: add learned RL value column (B2 value learning). A per-memory
-- scalar in [0,1] updated by TD credit assignment from session/rating outcomes
-- (Schultz 1997 RPE; Sutton & Barto 1998). 0.5 = neutral prior. Feeds
-- retention (high value resists decay) and retrieval priority.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'value'
    ) THEN
        ALTER TABLE memories ADD COLUMN value REAL DEFAULT 0.5;
    END IF;
END $$;

-- Migration: add source-monitoring attribution (C1 reality monitoring). The
-- epistemic origin of a memory — perceived (externally grounded) / told (user-
-- stated) / inferred (self-generated) / unknown — distinct from the `source`
-- ingestion-pathway column. Johnson, Hashtroudi & Lindsay 1993. Guards against
-- confabulation (inferred content asserted as observed).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'source_attribution'
    ) THEN
        ALTER TABLE memories ADD COLUMN source_attribution TEXT DEFAULT 'unknown';
    END IF;
END $$;

-- Migration: add capture origin (issue #365) — which CHANNEL produced the
-- content: deliberate (a user asked for it) / local_action (this machine's own
-- tools) / network (fetched off-machine, e.g. WebFetch/WebSearch) / unknown.
-- Resolved from the producing TOOL NAME at capture time, never inferred from
-- the content, so an off-machine payload cannot forge it. Distinct from BOTH
-- neighbours: `source` is the ingestion pathway, and `source_attribution` is
-- the epistemic origin that core/source_monitoring derives BY READING the
-- content — which is why neither can gate on trust. Governs whether the
-- content-derived write-gate bypasses may be claimed
-- (core/write_gate.determine_bypass).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'capture_origin'
    ) THEN
        ALTER TABLE memories
            ADD COLUMN capture_origin TEXT NOT NULL DEFAULT 'unknown';
        -- Backfill (issue #368). Every row present at this instant predates
        -- the attribute: its channel is not unknown, it was never recorded.
        -- Marking it 'legacy' keeps it at full ranking weight, where the
        -- DEFAULT 'unknown' would demote the entire historical corpus the
        -- moment the read-side trust factor ships. Inside the IF NOT EXISTS
        -- so it runs exactly once, on the upgrade that creates the column;
        -- rows written afterwards get 'unknown' from the DEFAULT and are
        -- demoted, which is the intended fail-closed behaviour for a channel
        -- nobody classified.
        UPDATE memories SET capture_origin = 'legacy';
    END IF;
END $$;

-- Migration: add habituation stimulus signature (E1 habituation &
-- sensitization). A normalised content-identity key; repeated presentations of
-- the same signature drive the write gate's exponential response decrement, so
-- near-duplicate low-salience churn is suppressed rather than re-admitted
-- (Rankin 2009). Distinct from `source` / `source_attribution`.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'stimulus_signature'
    ) THEN
        ALTER TABLE memories ADD COLUMN stimulus_signature TEXT DEFAULT '';
    END IF;
END $$;

-- Migration: add reversible inhibitory extinction tag (E2 fear extinction /
-- inhibitory learning). A scalar in [0,1]: 0 = no extinction (default, no
-- behaviour change); higher = the learned association is suppressed WITHOUT
-- deletion, so it spontaneously recovers (decay) or is reinstated (cleared).
-- Distinct from is_stale (active_forgetting's soft-delete): extinction leaves
-- the memory fully present and only lowers its effective retrieval weight
-- (Bouton 2004; Milad & Quirk 2012).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'extinction_strength'
    ) THEN
        ALTER TABLE memories ADD COLUMN extinction_strength REAL DEFAULT 0.0;
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

-- Migration: add explicit supersession edges (borrow-from-supermemory item 1).
-- supersedes_id points at the older fact this row replaces; superseded_by_id
-- points at the newer fact that replaced this row (head-of-chain has it NULL).
-- Additive to the reconsolidation model, not a replacement. Self-referential
-- FK with ON DELETE SET NULL so a hard-deleted version leaves no dangling
-- pointer. Both nullable, default NULL, so every existing and benchmark row
-- is unchanged -- benchmark-neutral by construction.
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

-- Migration: add stage_entered_at for real-time cascade tracking
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'stage_entered_at'
    ) THEN
        ALTER TABLE memories ADD COLUMN stage_entered_at TIMESTAMPTZ;
        -- Backfill: set to created_at for existing memories
        UPDATE memories SET stage_entered_at = created_at
            WHERE stage_entered_at IS NULL;
    END IF;
END $$;

-- Migration: add ingested_at for consolidation cadence reasoning.
-- Source: docs/benchmarks/e1-v3-locomo-smoke-finding.md.
-- created_at = original event/utterance time (may be backdated on import).
-- ingested_at = when the row entered THIS Cortex DB (always NOW at insert).
-- Compression and decay cadence MUST use ingested_at: the mechanism asks
-- "has this memory had time to be revisited in MY system" not "when did
-- the original event happen". Backfill existing rows from created_at to
-- preserve idempotency and pre-existing semantics.
-- NOTE keep this comment free of semicolons (DDL is split on the literal
-- character per _split_statements — df14e16 and 9f94bd3 are prior
-- incidents of that class).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'memories' AND column_name = 'ingested_at'
    ) THEN
        ALTER TABLE memories ADD COLUMN ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        -- Backfill rows that pre-existed this column. They were created
        -- before ingested_at was tracked, so the safest assumption is
        -- ingested_at = created_at (i.e., they entered the system at the
        -- time their content was authored). This block runs only inside
        -- the IF NOT EXISTS guard, so it is naturally idempotent.
        UPDATE memories SET ingested_at = created_at;
    END IF;
END $$;

-- Migration: persist arousal and dominant_emotion from emotional tagging
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

-- Migration: domain normalization trigger
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

-- ── Streaming-ingest support (sharded-popping-harbor refactor) ────────────
-- Source: ~/.claude/plans/sharded-popping-harbor.md (genius-verified A3).
-- The StagingResolveSink resolves entity/edge ids inside PG. The entity stage
-- is single-writer and resolves via NOT EXISTS, so it needs only a NON-unique
-- functional index to keep the LOWER(name) lookup index-backed — safe to
-- create unconditionally (never fails on existing case-variant duplicates).
CREATE INDEX IF NOT EXISTS idx_entities_lower_name ON entities (LOWER(name));

-- The edge stage runs concurrency=2 and upserts via ON CONFLICT, so it needs a
-- UNIQUE index on the directed tuple. Without it, re-ingest after a crash
-- silently DUPLICATES every 'calls'/'contains' edge (genius Dijkstra D2). The
-- existing unique index is PARTIAL (co_retrieval only); add the full one.
-- Dedup keeps MIN(id) and touches only the relationships table — no cross-
-- table repointing (mirrors uq_relationships_canonical_co_retrieval above).
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

-- Checkpoint table for resumable ingest (genius Dijkstra D5): each batch's
-- writes and its progress update commit inside ONE conn.transaction(), so a
-- crashed run resumes from last_key_committed with no duplication.
CREATE TABLE IF NOT EXISTS ingest_progress (
    run_id text PRIMARY KEY,
    last_key_committed text NOT NULL DEFAULT '',
    rows_committed bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

-- Migration: trigger provenance (bounded-io Phase 2 F1). Distinguishes
-- user-created triggers ('create_trigger') from harvested ones
-- ('auto_extract') so future cleanups never have to guess. Pre-existing
-- rows keep '' (unattributable). The 2026-06-10 audit found 317 active
-- keyword_match triggers with 100%-garbage sampled conditions, all
-- harvested from raw tool dumps by write_post_store.extract_triggers —
-- see docs/provenance/bounded-io-phase2-design.md M1.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name='prospective_memories'
                   AND column_name='created_by')
    THEN ALTER TABLE prospective_memories ADD COLUMN created_by TEXT
        NOT NULL DEFAULT '';
    END IF;
END $$;

-- Migration: entity origin provenance (ast_symbol vs text_concept). Fuzzy
-- entity dedup (core.entity_dedup) must merge only text-extracted concepts;
-- AST-extracted code symbols (class/function/module names, dotted module paths)
-- share long prefixes and must never be label-fuzzy-merged (graphify #1205).
-- Backfill: rows whose type is a code-symbol kind, or whose name is a slash
-- path or a dotted module path (>= 2 dots, mirrors entity_dedup_filters.
-- is_structural_identifier), are ast_symbol; everything else stays text_concept.
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

-- Migration: harden the injection-receipts channel enum (blame path T2,
-- decision 4255039 correction 3). Tables created by the T1 DDL carry a
-- free-TEXT channel; the CHECK added here mirrors the CREATE TABLE
-- constraint above and handlers/injection_receipts.py INJECTION_CHANNELS.
-- T1 only ever wrote 'recall', a member of the enum, so validating
-- existing rows is safe.
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

-- Migration: add wiki.pages.documents_primary for DBs provisioned before
-- ADR-0051 (wiki.page_sources is created fresh via CREATE TABLE IF NOT
-- EXISTS above and needs no guard; this column was added to an
-- already-existing table). table_schema qualifies the lookup since
-- information_schema.columns is not schema-scoped by default.
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

-- Migration: widen wiki.page_sources.link_kind + .source CHECKs for
-- INC5.1 (ADR-0052 D4) on DBs provisioned before this change. The
-- CREATE TABLE above already carries 'finding'/'ap-pipeline' for fresh
-- databases; this DO block patches existing ones. Idempotent: skips if
-- the live constraint definition already contains 'finding' (pg_get_
-- constraintdef comparison, same pattern as the documents_primary
-- migration above using information_schema instead of pg_constraint).
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

-- Migration: widen wiki.page_sources.link_kind CHECK for 'extracted_from'
-- (5.1b, on top of INC5.1's 'finding'/'ap-pipeline' widening above) on
-- DBs provisioned before this change. The CREATE TABLE above already
-- carries 'extracted_from' for fresh databases; this DO block patches
-- existing ones (including ones that already ran the INC5.1 DO block
-- above and now have the 4-value constraint, not the original 3-value
-- one). Idempotent: skips if the live constraint already contains
-- 'extracted_from'.
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

-- Migration: one citation per (page, session) (T2-H4/INC5.4, D7/Q2). A
-- session that re-reads the same page must not re-trigger the +0.05
-- heat bump on every read (trg_wiki_citation_bump). Partial unique
-- index: rows with session_id='' (no window-session identity resolved,
-- e.g. non-interactive callers) are intentionally excluded — they carry
-- no CITED_IN provenance semantics and must not collide with each
-- other. CREATE UNIQUE INDEX IF NOT EXISTS is itself idempotent; no DO
-- block needed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_wiki_citations_page_session
    ON wiki.citations (page_id, session_id)
    WHERE session_id <> '';

-- Migration: one citation per (page, memory) (I6-D7/INC6.8 — "flux
-- avant" write-path). Distinct dedup key from uq_wiki_citations_page_
-- session above: that index dedups "was this page read in this
-- session" (CITED_IN semantics, memory_id is incidental — always the
-- page's own anchor memory). THIS index dedups "was this memory
-- reported as used to author this page" (DOCUMENTS semantics,
-- consumed by cortex-viz's _WIKI_MEMORY_LINKS_SQL) regardless of
-- session — a re-curation that reports the same memory_id again for
-- the same page must be a no-op, not a growing row count. The two
-- indexes are independent partial uniques on the same table; insert_
-- citation's INSERT omits an explicit conflict target (unqualified
-- ON CONFLICT DO NOTHING) so a single statement is safely deduped by
-- whichever of the two applies — Postgres infers the arbiter per-row
-- when no target is named. CREATE UNIQUE INDEX IF NOT EXISTS is
-- itself idempotent; no DO block needed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_wiki_citations_page_memory
    ON wiki.citations (page_id, memory_id)
    WHERE memory_id IS NOT NULL;

-- Migration: stratify homeostatic_state by write_class (M-D3, 7.1,
-- 2026-07-10). Pre-existing installs have homeostatic_state(domain PK,
-- factor, updated_at) — one row per domain, written by a fold that did
-- not distinguish write class and re-suppressed the deliberate class
-- (confirmed by SQL against the dev DB: 2026-07-10 19:22 fold, 1021 rows,
-- domain='', 511 post_tool_capture + 510 deliberate-class sources, same
-- UPDATE, same factor). One-shot migration, no read shim (arbitrage
-- user 2026-07-10): existing rows are relabeled write_class='auto' via
-- column DEFAULT during the ADD COLUMN — the honest label, since their
-- factor history was driven by a corpus that was 92% auto-capture by
-- volume (I6 audit) — not a placeholder read-time interpretation.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'homeostatic_state' AND column_name = 'write_class'
    ) THEN
        ALTER TABLE homeostatic_state ADD COLUMN write_class TEXT
            NOT NULL DEFAULT 'auto'
            CHECK (write_class IN ('auto', 'deliberate', 'derived', 'mechanical'));
        -- Old PK was (domain) alone; the CHECK above already guarantees
        -- every legacy row is 'auto', so dropping and re-adding as
        -- (domain, write_class) is a pure widening — no row loses its
        -- unique identity (there was at most one row per domain before).
        ALTER TABLE homeostatic_state DROP CONSTRAINT homeostatic_state_pkey;
        ALTER TABLE homeostatic_state ADD PRIMARY KEY (domain, write_class);
    END IF;
END $$;

-- Migration: explicit write_class column on memories (M-D2, 7.4,
-- 2026-07-11). Structural migration ONLY — adds the column with the
-- module's documented safe DEFAULT ('deliberate', see MEMORIES_DDL
-- comment above). This DO block does NOT reclassify existing rows from
-- their `source` value: unlike homeostatic_state (where every legacy row
-- was provably 'auto', a single constant), `memories.source` spans the
-- full M-D2 taxonomy (auto/deliberate/derived/mechanical source
-- prefixes) and reclassifying it correctly requires the same predicate
-- logic as mcp_server.shared.write_class.classify_write_class — DDL is
-- infrastructure/, which must not import core/ (Clean Architecture
-- dependency rule), so duplicating that logic here in raw SQL would be
-- a second classification path, exactly what the single-choke-point
-- design forbids. The one-shot data migration is instead a Python script
-- that imports classify_write_class directly: run
-- `uv run python scripts/backfill_write_class.py --apply` once after
-- this DDL applies (dry-run by default; idempotent — a second run finds
-- zero rows to change). Until that script runs, every pre-existing row
-- reads write_class='deliberate' (the DEFAULT) — the safe direction:
-- true auto-capture rows are conservatively excluded from homeostatic
-- folding (a delayed correction) rather than a deliberate row being
-- mistaken for foldable noise (the failure this design exists to
-- prevent — see homeostatic_apply.py::_apply_fold).
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

-- Migration: source_memory_id on memory_rules and prospective_memories
-- (M-D6, 7.6, 2026-07-11). Structural only — nullable, no backfill (no
-- pre-existing row was ever created via a promotion job, so NULL is
-- correct for all of them, not a placeholder needing later correction).
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

-- Migration: widen wiki.pages.status's CHECK to the full per-kind status
-- union. DBs provisioned before this change carry the narrower
-- ('seedling','budding','evergreen') constraint, which rejects every ADR
-- ('proposed'/'accepted'/...), specs ('draft'/'review'/...), and 'living'
-- status that the system itself writes into frontmatter — see the CREATE
-- TABLE comment above for the full provenance. Unconditional drop-then-add
-- is the idempotent form here (cheaper and more robust than diffing
-- pg_get_constraintdef's version-dependent textual output): dropping a
-- constraint that doesn't exist is a documented no-op via IF EXISTS, and
-- re-adding the same definition is safe on every rerun.
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
        # Strip leading SQL line comments and blank lines so a chunk that
        # begins with "-- foo\nCREATE TABLE ..." is not mistaken for the
        # comment text being the first SQL token. Also drop chunks that
        # are *entirely* comments / whitespace.
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
        PROCEDURAL_SKILLS_DDL,
        # MIGRATIONS_DDL runs BEFORE INDEXES_DDL so the heat→heat_base
        # rename lands before indexes on heat_base are created.
        MIGRATIONS_DDL,
        # CURRENT_MEMORIES_VIEW_DDL runs AFTER MIGRATIONS_DDL so databases
        # predating the supersession columns gain superseded_by_id before
        # the view referencing it is (re)created.
        CURRENT_MEMORIES_VIEW_DDL,
        INDEXES_DDL,
        # effective_stage() must be created before effective_heat(), which
        # calls it to derive the floor lazily on the read path. alpha_integral()
        # likewise must precede effective_heat(), which calls it for the decay
        # exponent (piecewise α-integral, monotonic forgetting).
        EFFECTIVE_STAGE_FN,
        ALPHA_INTEGRAL_FN,
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
    # Every element derives from the module-literal *_DDL blocks above;
    # _split_statements only strips comments/whitespace (regex ops erase
    # LiteralString provenance for the checker, so it is re-asserted here).
    return cast("list[LiteralString]", result)
