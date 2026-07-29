"""SQLite mirror of the PostgreSQL `wiki` schema (pg_schema.py::WIKI_SCHEMA_DDL).

SQLite has no schema namespaces, so `wiki.<table>` is flattened to
`wiki_<table>`; sqlite_sql_translate._translate_sql rewrites the SQL on the
way in (imported by sqlite_compat.py, issue #260), which is what lets the
52 modules that query these tables run unmodified on both backends.

Type mapping applied here (issue #206):

| PostgreSQL                  | SQLite                              |
|-----------------------------|-------------------------------------|
| BIGSERIAL / SERIAL PK       | INTEGER PRIMARY KEY AUTOINCREMENT   |
| TIMESTAMPTZ [DEFAULT NOW()] | TEXT [DEFAULT (datetime('now'))]    |
| JSONB                       | JSON  (decltype -> json.loads)      |
| INTEGER[] / BIGINT[]        | JSON  (decltype -> json.loads)      |
| BOOLEAN                     | INTEGER (0/1)                       |
| vector(384)                 | BLOB (no ANN index; see note)       |

The `JSON` decltype is load-bearing, not decorative: `sqlite_store` connects
with `detect_types=PARSE_DECLTYPES` and registers a converter for it, so
`entity_ids` comes back a `list[int]` exactly as psycopg returns an
`INTEGER[]`. Without it the column would return the string "[1,2]", which
call sites like wiki_emerge.py:220 (`for eid in c.get("entity_ids") or []`)
would iterate CHARACTER-WISE — silently producing garbage entity ids rather
than failing. Verified 2026-07-27.

`vector(384)` columns are kept as BLOB for column parity (`SELECT embedding`
resolves) but carry no ANN index: pgvector's HNSW has no SQLite equivalent,
and the sqlite-vec path used for `memories` needs a separate vec0 virtual
table. No wiki pipeline handler reads these columns today. GIN indexes are
likewise dropped — SQLite has no equivalent.
"""

from __future__ import annotations

WIKI_CLAIM_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS wiki_claim_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    session_id      TEXT NOT NULL DEFAULT '',
    text            TEXT NOT NULL,
    claim_type      TEXT NOT NULL DEFAULT 'assertion'
                    CHECK (claim_type IN (
                      'assertion','decision','observation','question',
                      'method','result','limitation','reference'
                    )),
    entity_ids      JSON NOT NULL DEFAULT '[]',
    evidence_refs   JSON NOT NULL DEFAULT '[]',
    confidence      REAL NOT NULL DEFAULT 0.5
                    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    embedding       BLOB,
    supersedes      INTEGER REFERENCES wiki_claim_events(id) ON DELETE SET NULL,
    extracted_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

WIKI_CONCEPTS_DDL = """
CREATE TABLE IF NOT EXISTS wiki_concepts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    label                   TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'candidate'
                            CHECK (status IN (
                              'candidate','saturating','promoted',
                              'merged','split','abandoned'
                            )),
    centroid_embedding      BLOB,
    entity_ids              JSON NOT NULL DEFAULT '[]',
    grounding_memory_ids    JSON NOT NULL DEFAULT '[]',
    grounding_claim_ids     JSON NOT NULL DEFAULT '[]',
    properties              JSON NOT NULL DEFAULT '{}',
    axial_slots             JSON NOT NULL DEFAULT '{}',
    saturation_rate         REAL NOT NULL DEFAULT 1.0,
    saturation_streak       INTEGER NOT NULL DEFAULT 0,
    first_seen_at           TEXT NOT NULL DEFAULT (datetime('now')),
    last_property_at        TEXT NOT NULL DEFAULT (datetime('now')),
    promoted_page_id        INTEGER,
    merged_into_id          INTEGER REFERENCES wiki_concepts(id) ON DELETE SET NULL,
    split_into_ids          JSON,
    core_category_link      INTEGER REFERENCES wiki_concepts(id) ON DELETE SET NULL
);
"""

WIKI_DRAFTS_DDL = """
CREATE TABLE IF NOT EXISTS wiki_drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id      INTEGER REFERENCES wiki_concepts(id) ON DELETE CASCADE,
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    kind            TEXT NOT NULL,
    lead            TEXT NOT NULL DEFAULT '',
    sections        JSON NOT NULL DEFAULT '{}',
    frontmatter     JSON NOT NULL DEFAULT '{}',
    provenance      JSON NOT NULL DEFAULT '{}',
    synth_prompt    TEXT,
    synth_model     TEXT,
    confidence      REAL NOT NULL DEFAULT 0.5,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','published')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at     TEXT,
    published_page_id INTEGER
);
"""

# status/lifecycle_state vocabularies mirror pg_schema.py's wiki.pages
# CHECK constraints verbatim — see that file for the provenance of each
# value (core/wiki_templates.py STATUS_VALUES, auto_curator 'living', etc.).
WIKI_PAGES_DDL = """
CREATE TABLE IF NOT EXISTS wiki_pages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id       INTEGER UNIQUE REFERENCES memories(id) ON DELETE SET NULL,
    concept_id      INTEGER REFERENCES wiki_concepts(id) ON DELETE SET NULL,
    documents_primary TEXT,
    rel_path        TEXT UNIQUE NOT NULL,
    slug            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    domain          TEXT NOT NULL DEFAULT '',
    domains         JSON NOT NULL DEFAULT '[]',
    tags            JSON NOT NULL DEFAULT '[]',
    audience        JSON NOT NULL DEFAULT '[]',
    requires        JSON NOT NULL DEFAULT '[]',
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
    sections        JSON NOT NULL DEFAULT '{}',
    body_hash       TEXT NOT NULL DEFAULT '',
    embedding       BLOB,
    heat            REAL NOT NULL DEFAULT 1.0
                    CHECK (heat >= 0.0 AND heat <= 1.0),
    access_count    INTEGER NOT NULL DEFAULT 0,
    citation_count  INTEGER NOT NULL DEFAULT 0,
    backlink_count  INTEGER NOT NULL DEFAULT 0,
    source_memory_heat REAL,
    is_stale        INTEGER NOT NULL DEFAULT 0,
    planted         TEXT NOT NULL DEFAULT (datetime('now')),
    tended          TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed_at TEXT,
    last_cited_at   TEXT,
    archived_at     TEXT
);
"""

WIKI_LINKS_DDL = """
CREATE TABLE IF NOT EXISTS wiki_links (
    src_page_id     INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    dst_slug        TEXT NOT NULL,
    dst_page_id     INTEGER REFERENCES wiki_pages(id) ON DELETE SET NULL,
    link_kind       TEXT NOT NULL DEFAULT 'see-also'
                    CHECK (link_kind IN (
                      'see-also','requires','supersedes','inline',
                      'contradicts','refines','benchmarks'
                    )),
    PRIMARY KEY (src_page_id, dst_slug, link_kind)
);
"""

WIKI_CITATIONS_DDL = """
CREATE TABLE IF NOT EXISTS wiki_citations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id         INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL DEFAULT '',
    domain          TEXT NOT NULL DEFAULT '',
    memory_id       INTEGER REFERENCES memories(id) ON DELETE SET NULL,
    cited_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

WIKI_PAGE_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS wiki_page_sources (
    page_id         INTEGER NOT NULL REFERENCES wiki_pages(id) ON DELETE CASCADE,
    source_path     TEXT NOT NULL,
    symbol          TEXT,
    link_kind       TEXT NOT NULL DEFAULT 'documents'
                    CHECK (link_kind IN (
                      'documents','references','derived','finding','extracted_from'
                    )),
    confidence      REAL NOT NULL DEFAULT 1.0,
    source          TEXT NOT NULL DEFAULT 'frontmatter'
                    CHECK (source IN (
                      'frontmatter','claim_evidence','body','codebase_grounding',
                      'ap-pipeline'
                    )),
    PRIMARY KEY (page_id, source_path, link_kind)
);
"""

WIKI_MEMOS_DDL = """
CREATE TABLE IF NOT EXISTS wiki_memos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type    TEXT NOT NULL
                    CHECK (subject_type IN ('concept','draft','page','claim')),
    subject_id      INTEGER NOT NULL,
    decision        TEXT NOT NULL,
    rationale       TEXT NOT NULL DEFAULT '',
    alternatives    JSON NOT NULL DEFAULT '[]',
    inputs          JSON NOT NULL DEFAULT '{}',
    confidence      REAL NOT NULL DEFAULT 0.5,
    author          TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Index parity with pg_schema.py minus the two PostgreSQL-only families:
# HNSW (pgvector ANN) and GIN (tags containment). Partial indexes are kept —
# SQLite supports them — with `NOT is_stale` rewritten to `is_stale = 0`
# because is_stale is INTEGER here, not BOOLEAN.
WIKI_INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_memory "
    "ON wiki_claim_events (memory_id);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_claim_events_session "
    "ON wiki_claim_events (session_id);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_concepts_status "
    "ON wiki_concepts (status) WHERE status IN ('candidate','saturating');",
    "CREATE INDEX IF NOT EXISTS idx_wiki_drafts_status "
    "ON wiki_drafts (status) WHERE status = 'pending';",
    "CREATE INDEX IF NOT EXISTS idx_wiki_pages_kind_status_domain "
    "ON wiki_pages (kind, status, domain);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_pages_lifecycle_domain "
    "ON wiki_pages (lifecycle_state, domain) "
    "WHERE lifecycle_state IN ('active','evergreen');",
    "CREATE INDEX IF NOT EXISTS idx_wiki_pages_heat "
    "ON wiki_pages (heat DESC) WHERE is_stale = 0;",
    "CREATE INDEX IF NOT EXISTS idx_wiki_links_dst "
    "ON wiki_links (dst_page_id) WHERE dst_page_id IS NOT NULL;",
    "CREATE INDEX IF NOT EXISTS idx_wiki_links_dst_slug ON wiki_links (dst_slug);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_page_sources_path "
    "ON wiki_page_sources (source_path);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_citations_page_time "
    "ON wiki_citations (page_id, cited_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_citations_session "
    "ON wiki_citations (session_id);",
    "CREATE INDEX IF NOT EXISTS idx_wiki_memos_subject "
    "ON wiki_memos (subject_type, subject_id);",
]

# Order matters: wiki_concepts and wiki_pages precede the tables whose
# foreign keys reference them (PRAGMA foreign_keys=ON is set on connect).
WIKI_TABLE_DDL = [
    WIKI_CLAIM_EVENTS_DDL,
    WIKI_CONCEPTS_DDL,
    WIKI_DRAFTS_DDL,
    WIKI_PAGES_DDL,
    WIKI_LINKS_DDL,
    WIKI_CITATIONS_DDL,
    WIKI_PAGE_SOURCES_DDL,
    WIKI_MEMOS_DDL,
]


def get_wiki_ddl() -> list[str]:
    """Every wiki DDL statement, tables before indexes."""
    return [*WIKI_TABLE_DDL, *WIKI_INDEXES_DDL]
