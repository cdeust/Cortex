"""Schema initialization and migration for the memory SQLite database."""

from __future__ import annotations

import sqlite3


_CORE_TABLES_DDL = """
    CREATE TABLE IF NOT EXISTS memories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        embedding BLOB,
        tags TEXT DEFAULT '[]',
        source TEXT DEFAULT '',
        domain TEXT DEFAULT '',
        directory_context TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        last_accessed TEXT NOT NULL,
        heat REAL DEFAULT 1.0,
        surprise_score REAL DEFAULT 0.0,
        importance REAL DEFAULT 0.5,
        emotional_valence REAL DEFAULT 0.0,
        confidence REAL DEFAULT 1.0,
        access_count INTEGER DEFAULT 0,
        useful_count INTEGER DEFAULT 0,
        plasticity REAL DEFAULT 1.0,
        stability REAL DEFAULT 0.0,
        reconsolidation_count INTEGER DEFAULT 0,
        last_reconsolidated TEXT,
        store_type TEXT DEFAULT 'episodic',
        compressed INTEGER DEFAULT 0,
        compression_level INTEGER DEFAULT 0,
        original_content TEXT,
        is_protected INTEGER DEFAULT 0,
        is_stale INTEGER DEFAULT 0,
        slot_index INTEGER,
        excitability REAL DEFAULT 1.0,
        consolidation_stage TEXT DEFAULT 'labile',
        hours_in_stage REAL DEFAULT 0.0,
        replay_count INTEGER DEFAULT 0,
        theta_phase_at_encoding REAL DEFAULT 0.0,
        encoding_strength REAL DEFAULT 1.0,
        separation_index REAL DEFAULT 0.0,
        interference_score REAL DEFAULT 0.0,
        schema_match_score REAL DEFAULT 0.0,
        schema_id TEXT,
        hippocampal_dependency REAL DEFAULT 1.0
    );

    CREATE TABLE IF NOT EXISTS entities(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        domain TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        last_accessed TEXT NOT NULL,
        heat REAL DEFAULT 1.0,
        archived INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS relationships(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_entity_id INTEGER NOT NULL,
        target_entity_id INTEGER NOT NULL,
        relationship_type TEXT NOT NULL,
        weight REAL DEFAULT 1.0,
        is_causal INTEGER DEFAULT 0,
        confidence REAL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        last_reinforced TEXT NOT NULL,
        release_probability REAL DEFAULT 0.5,
        facilitation REAL DEFAULT 0.0,
        depression REAL DEFAULT 0.0,
        FOREIGN KEY(source_entity_id) REFERENCES entities(id),
        FOREIGN KEY(target_entity_id) REFERENCES entities(id)
    );
"""

_SUPPORT_TABLES_DDL = """
    CREATE TABLE IF NOT EXISTS prospective_memories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        trigger_condition TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        target_directory TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL,
        triggered_at TEXT,
        triggered_count INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS checkpoints(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT DEFAULT 'default',
        directory_context TEXT DEFAULT '',
        current_task TEXT DEFAULT '',
        files_being_edited TEXT DEFAULT '[]',
        key_decisions TEXT DEFAULT '[]',
        open_questions TEXT DEFAULT '[]',
        next_steps TEXT DEFAULT '[]',
        active_errors TEXT DEFAULT '[]',
        custom_context TEXT DEFAULT '',
        epoch INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS memory_archives(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_memory_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        embedding BLOB,
        archived_at TEXT NOT NULL,
        mismatch_score REAL DEFAULT 0.0,
        archive_reason TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS consolidation_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        memories_added INTEGER DEFAULT 0,
        memories_updated INTEGER DEFAULT 0,
        memories_archived INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS engram_slots(
        slot_index INTEGER PRIMARY KEY,
        excitability REAL DEFAULT 0.5,
        last_activated TEXT
    );

    CREATE TABLE IF NOT EXISTS memory_rules(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_type TEXT NOT NULL DEFAULT 'soft',
        scope TEXT NOT NULL DEFAULT 'global',
        scope_value TEXT,
        condition TEXT NOT NULL,
        action TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    );
"""

_INDEXES_DDL = """
    CREATE INDEX IF NOT EXISTS idx_memories_heat ON memories(heat);
    CREATE INDEX IF NOT EXISTS idx_memories_domain ON memories(domain);
    CREATE INDEX IF NOT EXISTS idx_memories_store_type ON memories(store_type);
    CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
    CREATE INDEX IF NOT EXISTS idx_entities_heat ON entities(heat);
    CREATE INDEX IF NOT EXISTS idx_prospective_active
        ON prospective_memories(is_active);
"""

_SCHEMAS_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS schemas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schema_id TEXT UNIQUE NOT NULL,
        domain TEXT DEFAULT '',
        label TEXT DEFAULT '',
        entity_signature TEXT DEFAULT '{}',
        relationship_types TEXT DEFAULT '[]',
        tag_signature TEXT DEFAULT '{}',
        consistency_threshold REAL DEFAULT 0.7,
        formation_count INTEGER DEFAULT 0,
        assimilation_count INTEGER DEFAULT 0,
        violation_count INTEGER DEFAULT 0,
        last_updated TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS oscillatory_state(
        id INTEGER PRIMARY KEY CHECK (id = 1),
        state_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE INDEX IF NOT EXISTS idx_schemas_domain ON schemas(domain);
"""

_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("memories", "consolidation_stage", "TEXT DEFAULT 'labile'"),
    ("memories", "hours_in_stage", "REAL DEFAULT 0.0"),
    ("memories", "replay_count", "INTEGER DEFAULT 0"),
    ("memories", "theta_phase_at_encoding", "REAL DEFAULT 0.0"),
    ("memories", "encoding_strength", "REAL DEFAULT 1.0"),
    ("memories", "separation_index", "REAL DEFAULT 0.0"),
    ("memories", "interference_score", "REAL DEFAULT 0.0"),
    ("memories", "schema_match_score", "REAL DEFAULT 0.0"),
    ("memories", "schema_id", "TEXT"),
    ("memories", "hippocampal_dependency", "REAL DEFAULT 1.0"),
    ("relationships", "release_probability", "REAL DEFAULT 0.5"),
    ("relationships", "facilitation", "REAL DEFAULT 0.0"),
    ("relationships", "depression", "REAL DEFAULT 0.0"),
]


def init_schema(conn: sqlite3.Connection, has_vec: bool, dim: int) -> None:
    """Create all tables, indexes, FTS5, and optional vec0 virtual table."""
    conn.executescript(_CORE_TABLES_DDL)
    conn.executescript(_SUPPORT_TABLES_DDL)
    conn.executescript(_INDEXES_DDL)
    conn.executescript(_SCHEMAS_TABLE_DDL)

    _create_fts_table(conn)
    if has_vec:
        _create_vec_table(conn, dim)
    conn.commit()

    _run_migrations(conn)


def _create_fts_table(conn: sqlite3.Connection) -> None:
    """Create the FTS5 virtual table for full-text search."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE memories_fts USING fts5(content, content_rowid='id')"
        )
    except sqlite3.OperationalError:
        pass  # already exists


def _create_vec_table(conn: sqlite3.Connection, dim: int) -> None:
    """Create the sqlite-vec virtual table for KNN search."""
    try:
        conn.execute(
            f"CREATE VIRTUAL TABLE memory_vectors USING vec0(embedding float[{dim}])"
        )
    except sqlite3.OperationalError:
        pass  # already exists


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add columns for neuroscience evolution (non-destructive ALTER TABLE).

    Each migration checks if the column already exists before adding it.
    Safe to run repeatedly on existing databases.
    """
    for table, column, col_def in _COLUMN_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memories_stage "
            "ON memories(consolidation_stage)"
        )
    except sqlite3.OperationalError:
        pass

    conn.commit()
