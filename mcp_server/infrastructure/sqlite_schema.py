"""SQLite schema: DDL for fallback storage when PostgreSQL is unavailable.

Translates pg_schema.py tables to SQLite-compatible DDL.
Uses FTS5 for full-text search and sqlite-vec for vector similarity.

Pure DDL — no connection management.
"""

from __future__ import annotations

# ── Core Tables ───────────────────────────────────────────────────────────

MEMORIES_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    content                 TEXT NOT NULL,
    tags                    TEXT DEFAULT '[]',
    source                  TEXT DEFAULT '',
    domain                  TEXT DEFAULT '',
    directory_context       TEXT DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed           TEXT NOT NULL DEFAULT (datetime('now')),
    heat_base               REAL NOT NULL DEFAULT 1.0
                            CHECK (heat_base >= 0.0 AND heat_base <= 1.0),
    heat_base_set_at        TEXT NOT NULL DEFAULT (datetime('now')),
    no_decay                INTEGER NOT NULL DEFAULT 0,
    surprise_score          REAL DEFAULT 0.0,
    importance              REAL DEFAULT 0.5,
    emotional_valence       REAL DEFAULT 0.0,
    confidence              REAL DEFAULT 1.0,
    access_count            INTEGER DEFAULT 0,
    useful_count            INTEGER DEFAULT 0,
    plasticity              REAL DEFAULT 1.0,
    stability               REAL DEFAULT 0.0,
    reconsolidation_count   INTEGER DEFAULT 0,
    last_reconsolidated     TEXT,
    store_type              TEXT DEFAULT 'episodic',
    compressed              INTEGER DEFAULT 0,
    compression_level       INTEGER DEFAULT 0,
    original_content        TEXT,
    is_protected            INTEGER DEFAULT 0,
    is_stale                INTEGER DEFAULT 0,
    slot_index              INTEGER,
    excitability            REAL DEFAULT 1.0,
    consolidation_stage     TEXT DEFAULT 'labile',
    hours_in_stage          REAL DEFAULT 0.0,
    replay_count            INTEGER DEFAULT 0,
    theta_phase_at_encoding REAL DEFAULT 0.0,
    encoding_strength       REAL DEFAULT 1.0,
    separation_index        REAL DEFAULT 0.0,
    interference_score      REAL DEFAULT 0.0,
    schema_match_score      REAL DEFAULT 0.0,
    schema_id               TEXT,
    hippocampal_dependency  REAL DEFAULT 1.0,
    is_benchmark            INTEGER DEFAULT 0,
    agent_context           TEXT DEFAULT '',
    is_global               INTEGER DEFAULT 0
);
"""

HOMEOSTATIC_STATE_DDL = """
CREATE TABLE IF NOT EXISTS homeostatic_state (
    domain      TEXT PRIMARY KEY,
    factor      REAL NOT NULL DEFAULT 1.0
                CHECK (factor > 0.0 AND factor < 10.0),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

MEMORIES_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='id'
);
"""

MEMORIES_VEC_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
    embedding float[384]
);
"""

ENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    domain          TEXT DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_accessed   TEXT NOT NULL DEFAULT (datetime('now')),
    heat            REAL DEFAULT 1.0,
    archived        INTEGER DEFAULT 0,
    -- Provenance mirror of the PG schema: 'ast_symbol' vs 'text_concept'.
    -- Consumed by core.entity_dedup to exempt code symbols from fuzzy dedup.
    origin          TEXT NOT NULL DEFAULT 'text_concept'
);
"""

RELATIONSHIPS_DDL = """
CREATE TABLE IF NOT EXISTS relationships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_entity_id    INTEGER NOT NULL REFERENCES entities(id),
    target_entity_id    INTEGER NOT NULL REFERENCES entities(id),
    relationship_type   TEXT NOT NULL,
    weight              REAL DEFAULT 1.0,
    is_causal           INTEGER DEFAULT 0,
    confidence          REAL DEFAULT 1.0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    last_reinforced     TEXT NOT NULL DEFAULT (datetime('now')),
    release_probability REAL DEFAULT 0.5,
    facilitation        REAL DEFAULT 0.0,
    depression          REAL DEFAULT 0.0
);
"""

STAGE_TRANSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS stage_transitions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id           INTEGER NOT NULL,
    from_stage          TEXT NOT NULL,
    to_stage            TEXT NOT NULL,
    hours_in_prev_stage REAL DEFAULT 0.0,
    trigger             TEXT DEFAULT 'cascade',
    transitioned_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

MEMORY_ENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id   INTEGER NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (memory_id, entity_id)
);
"""

PROSPECTIVE_MEMORIES_DDL = """
CREATE TABLE IF NOT EXISTS prospective_memories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    content             TEXT NOT NULL,
    trigger_condition   TEXT NOT NULL,
    trigger_type        TEXT NOT NULL,
    target_directory    TEXT,
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    triggered_at        TEXT,
    triggered_count     INTEGER DEFAULT 0,
    created_by          TEXT NOT NULL DEFAULT ''
);
"""

CHECKPOINTS_DDL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT DEFAULT 'default',
    directory_context   TEXT DEFAULT '',
    current_task        TEXT DEFAULT '',
    files_being_edited  TEXT DEFAULT '[]',
    key_decisions       TEXT DEFAULT '[]',
    open_questions      TEXT DEFAULT '[]',
    next_steps          TEXT DEFAULT '[]',
    active_errors       TEXT DEFAULT '[]',
    custom_context      TEXT DEFAULT '',
    epoch               INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    is_active           INTEGER DEFAULT 1
);
"""

MEMORY_ARCHIVES_DDL = """
CREATE TABLE IF NOT EXISTS memory_archives (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    original_memory_id  INTEGER NOT NULL,
    content             TEXT NOT NULL,
    archived_at         TEXT NOT NULL DEFAULT (datetime('now')),
    mismatch_score      REAL DEFAULT 0.0,
    archive_reason      TEXT DEFAULT ''
);
"""

CONSOLIDATION_LOG_DDL = """
CREATE TABLE IF NOT EXISTS consolidation_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    memories_added      INTEGER DEFAULT 0,
    memories_updated    INTEGER DEFAULT 0,
    memories_archived   INTEGER DEFAULT 0,
    duration_ms         INTEGER DEFAULT 0
);
"""

ENGRAM_SLOTS_DDL = """
CREATE TABLE IF NOT EXISTS engram_slots (
    slot_index          INTEGER PRIMARY KEY,
    excitability        REAL DEFAULT 0.5,
    last_activated      TEXT
);
"""

MEMORY_RULES_DDL = """
CREATE TABLE IF NOT EXISTS memory_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type           TEXT NOT NULL DEFAULT 'soft',
    scope               TEXT NOT NULL DEFAULT 'global',
    scope_value         TEXT,
    condition           TEXT NOT NULL,
    action              TEXT NOT NULL,
    priority            INTEGER DEFAULT 0,
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

SCHEMAS_DDL = """
CREATE TABLE IF NOT EXISTS schemas (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_id               TEXT UNIQUE NOT NULL,
    domain                  TEXT DEFAULT '',
    label                   TEXT DEFAULT '',
    entity_signature        TEXT DEFAULT '{}',
    relationship_types      TEXT DEFAULT '[]',
    tag_signature           TEXT DEFAULT '{}',
    consistency_threshold   REAL DEFAULT 0.7,
    formation_count         INTEGER DEFAULT 0,
    assimilation_count      INTEGER DEFAULT 0,
    violation_count         INTEGER DEFAULT 0,
    last_updated            TEXT NOT NULL DEFAULT (datetime('now')),
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

OSCILLATORY_STATE_DDL = """
CREATE TABLE IF NOT EXISTS oscillatory_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    state_json  TEXT NOT NULL DEFAULT '{}'
);
"""

# User session-level mood state for MOOD_CONGRUENT_RERANK (Bower 1981).
# Mirrors pg_schema.py user_mood table. The seed row defaults to neutral
# so the pg_recall._get_user_mood() bridge gets a real signal instead of
# always returning None.
# Split into two separate DDL statements because sqlite3.Connection.execute()
# accepts only one statement at a time (unlike executescript).
# Source: Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
USER_MOOD_DDL = """
CREATE TABLE IF NOT EXISTS user_mood (
    user_id     TEXT PRIMARY KEY DEFAULT 'default',
    valence     REAL NOT NULL DEFAULT 0.0
                CHECK (valence >= -1.0 AND valence <= 1.0),
    arousal     REAL NOT NULL DEFAULT 0.0
                CHECK (arousal >= -1.0 AND arousal <= 1.0),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""

# Seed the default neutral mood row. Engineering choice: this INSERT is a
# separate DDL so _init_schema's per-statement try/except loop handles it
# individually — a conflict on an existing row is silently skipped.
USER_MOOD_SEED_DDL = """
INSERT OR IGNORE INTO user_mood (user_id, valence, arousal)
VALUES ('default', 0.0, 0.0)
"""

# ── Indexes ───────────────────────────────────────────────────────────────
# Each index is a separate string so _init_schema's per-statement loop
# executes all of them. sqlite3.Connection.execute() runs only the first
# statement of a multi-statement string; a single large INDEXES_DDL would
# silently create only the first index and discard the rest.

INDEXES_DDL: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_memories_heat_base ON memories (heat_base)",
    "CREATE INDEX IF NOT EXISTS idx_memories_domain ON memories (domain)",
    "CREATE INDEX IF NOT EXISTS idx_memories_store_type ON memories (store_type)",
    "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memories_stage ON memories (consolidation_stage)",
    "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities (name)",
    "CREATE INDEX IF NOT EXISTS idx_entities_heat ON entities (heat)",
    "CREATE INDEX IF NOT EXISTS idx_prospective_active ON prospective_memories (is_active)",
    "CREATE INDEX IF NOT EXISTS idx_schemas_domain ON schemas (domain)",
    "CREATE INDEX IF NOT EXISTS idx_rel_pair_type ON relationships (source_entity_id, target_entity_id, relationship_type)",
    "CREATE INDEX IF NOT EXISTS idx_memories_agent_context ON memories (agent_context)",
]


def get_all_ddl() -> list[str]:
    """Return all DDL statements in execution order.

    Note: FTS5 and vec0 virtual tables are returned separately
    so callers can skip vec0 if sqlite-vec is not available.

    INDEXES_DDL is a list of individual CREATE INDEX statements so that
    _init_schema's per-statement loop creates every index. A single
    multi-statement string passed to sqlite3.execute() would silently
    run only the first statement.
    """
    return [
        MEMORIES_DDL,
        HOMEOSTATIC_STATE_DDL,
        MEMORIES_FTS_DDL,
        # MEMORIES_VEC_DDL is handled separately — requires sqlite-vec
        ENTITIES_DDL,
        RELATIONSHIPS_DDL,
        MEMORY_ENTITIES_DDL,
        STAGE_TRANSITIONS_DDL,
        PROSPECTIVE_MEMORIES_DDL,
        CHECKPOINTS_DDL,
        MEMORY_ARCHIVES_DDL,
        CONSOLIDATION_LOG_DDL,
        ENGRAM_SLOTS_DDL,
        MEMORY_RULES_DDL,
        SCHEMAS_DDL,
        OSCILLATORY_STATE_DDL,
        USER_MOOD_DDL,
        USER_MOOD_SEED_DDL,
        *INDEXES_DDL,
    ]


# ── Migrations ───────────────────────────────────────────────────────────
# Each migration adds columns that may be missing from older databases.
# Format: (table, column, type_and_default)

MIGRATIONS: list[tuple[str, str, str]] = [
    ("memories", "is_benchmark", "INTEGER DEFAULT 0"),
    ("memories", "agent_context", "TEXT DEFAULT ''"),
    ("memories", "is_global", "INTEGER DEFAULT 0"),
    ("memories", "stage_entered_at", "TEXT"),
    # Trigger provenance (bounded-io Phase 2 F1) — PG parity with the
    # prospective_memories.created_by migration in pg_schema.py.
    ("prospective_memories", "created_by", "TEXT NOT NULL DEFAULT ''"),
    # Memory supersession chain (P0-1a parity) — mirrors pg_schema.py
    # supersedes_id / superseded_by_id columns added in MIGRATIONS_DDL.
    # SQLite does not enforce FK on ADD COLUMN; the FK is declared for
    # documentation but will not be enforced at this site.
    ("memories", "supersedes_id", "INTEGER"),
    ("memories", "superseded_by_id", "INTEGER"),
]
