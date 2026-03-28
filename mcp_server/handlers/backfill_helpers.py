"""Helpers for backfill_memories -- file discovery, hashing, and concept linking.

Extracted from backfill_memories.py to keep both files under 300 lines.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.infrastructure.memory_store import MemoryStore

# Core concept keywords for entity linking
_CORE_CONCEPTS = {
    "predictive_coding": [
        "predictive coding",
        "write gate",
        "novelty score",
        "embedding novelty",
    ],
    "hopfield": ["hopfield", "modern hopfield", "pattern matrix"],
    "hdc": ["hyperdimensional", "hdc", "bind bundle permute", "bipolar vector"],
    "successor_representation": [
        "successor representation",
        "co-access",
        "sr graph",
        "sr score",
    ],
    "thermodynamics": ["heat decay", "thermodynamic", "cold threshold", "heat score"],
    "consolidation": [
        "cls consolidation",
        "episodic to semantic",
        "memify",
        "sleep compute",
    ],
    "fractal_hierarchy": [
        "fractal hierarchy",
        "recall hierarchical",
        "drill down",
        "cluster",
    ],
    "knowledge_graph": [
        "entity relationship",
        "causal chain",
        "knowledge graph",
        "entity extraction",
    ],
}


# -- Backfill log --


def ensure_backfill_log(store: MemoryStore) -> None:
    """Create the backfill_log table if it doesn't exist."""
    from mcp_server.infrastructure.sql_compat import execute, commit, is_sqlite

    if is_sqlite(store._conn):
        execute(store._conn,
            """CREATE TABLE IF NOT EXISTS backfill_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,
                memories_imported INTEGER DEFAULT 0,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
    else:
        execute(store._conn,
            """CREATE TABLE IF NOT EXISTS backfill_log (
                id SERIAL PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                file_hash TEXT NOT NULL,
                memories_imported INTEGER DEFAULT 0,
                processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )""")
    commit(store._conn)


def file_hash(path: Path) -> str:
    """Compute a fast hash of the first 64 KB of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read(65536))
    return h.hexdigest()[:16]


def is_already_backfilled(store: MemoryStore, path: Path, current_hash: str) -> bool:
    """Check whether a file has already been backfilled with this hash."""
    from mcp_server.infrastructure.sql_compat import fetchone

    row = fetchone(store._conn,
        "SELECT file_hash FROM backfill_log WHERE file_path = %s",
        (str(path),),
    )
    if row is None:
        return False
    return row["file_hash"] == current_hash


def mark_backfilled(store: MemoryStore, path: Path, fhash: str, count: int) -> None:
    """Record that a file has been backfilled."""
    from mcp_server.infrastructure.sql_compat import execute

    execute(store._conn,
        """INSERT INTO backfill_log (file_path, file_hash, memories_imported, processed_at)
           VALUES (%s, %s, %s, NOW())
           ON CONFLICT(file_path) DO UPDATE SET
             file_hash = EXCLUDED.file_hash,
             memories_imported = EXCLUDED.memories_imported,
             processed_at = NOW()
        """,
        (str(path), fhash, count),
    )
    store._conn.commit()


# -- File discovery --


def discover_files(project_filter: str, max_files: int) -> list[tuple[Path, str]]:
    """Return (path, project_slug) pairs for JSONL session files."""
    projects_dir = CLAUDE_DIR / "projects"
    if not projects_dir.exists():
        return []

    results: list[tuple[Path, str]] = []
    limit = max_files * 3  # over-fetch, filter later

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        slug = project_dir.name
        if project_filter and project_filter not in slug:
            continue
        for jsonl_file in sorted(project_dir.glob("*.jsonl"), reverse=True):
            results.append((jsonl_file, slug))
            if len(results) >= limit:
                break

    return results[:limit]


def slug_to_domain(slug: str) -> str:
    """Convert a project slug like '-Users-you-project-name' to a domain hint."""
    parts = [p for p in slug.split("-") if p and len(p) > 2]
    return parts[-1] if parts else slug[:20]


# -- Concept linking --


def find_concepts(content: str) -> list[str]:
    """Return core concept keys that appear in the content."""
    lower = content.lower()
    return [
        key
        for key, keywords in _CORE_CONCEPTS.items()
        if any(kw in lower for kw in keywords)
    ]


def _upsert_concept_entity(store: MemoryStore, concept: str) -> int | None:
    """Find or create an entity for a core concept. Returns entity_id."""
    entity_name = f"cortex:{concept}"
    existing = store.get_entity_by_name(entity_name)
    if existing:
        return existing["id"]
    try:
        return store.insert_entity(
            {
                "name": entity_name,
                "type": "concept",
                "domain": "cortex",
                "heat": 0.8,
            }
        )
    except Exception:
        return None


def link_concepts(store: MemoryStore, memory_id: int, concepts: list[str]) -> int:
    """Create entity relationships linking a memory to core concepts."""
    linked = 0
    for concept in concepts:
        entity_id = _upsert_concept_entity(store, concept)
        if entity_id is None:
            continue
        try:
            store.insert_relationship(
                {
                    "source_entity_id": memory_id,
                    "target_entity_id": entity_id,
                    "relationship_type": "mentions_concept",
                    "weight": 0.8,
                    "confidence": 0.7,
                }
            )
            linked += 1
        except Exception:
            pass
    return linked
