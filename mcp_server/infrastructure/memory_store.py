"""SQLite-backed memory storage engine with FTS5 full-text search.

Provides all persistence for the memory subsystem:
- Memories with thermodynamic properties
- Entities and relationships (knowledge graph)
- Prospective triggers, checkpoints, archives, engram slots
- Consolidation log, rules, schemas

Uses WAL mode for concurrent access. All I/O is synchronous (SQLite).
Vector search via sqlite-vec when available, fallback to brute-force.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.memory_store_auxiliary import (
    MemoryAuxiliaryMixin,
)
from mcp_server.infrastructure.memory_store_entities import MemoryEntityMixin
from mcp_server.infrastructure.memory_store_queries import MemoryQueryMixin
from mcp_server.infrastructure.memory_store_relationships import (
    MemoryRelationshipMixin,
)
from mcp_server.infrastructure.memory_store_rules import MemoryRuleMixin
from mcp_server.infrastructure.memory_store_schema_init import init_schema
from mcp_server.infrastructure.memory_store_schemas import MemorySchemaMixin
from mcp_server.infrastructure.memory_store_search import MemorySearchMixin
from mcp_server.infrastructure.memory_store_stats import MemoryStatsMixin


class MemoryStore(
    MemorySearchMixin,
    MemoryEntityMixin,
    MemoryRelationshipMixin,
    MemoryRuleMixin,
    MemorySchemaMixin,
    MemoryStatsMixin,
    MemoryAuxiliaryMixin,
    MemoryQueryMixin,
):
    """SQLite storage engine for JARVIS memory system."""

    def __init__(self, db_path: str, embedding_dim: int = 384) -> None:
        resolved = Path(db_path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._embedding_dim = embedding_dim
        self._has_vec = False

        self._conn = sqlite3.connect(str(resolved), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._try_load_vec()
        init_schema(self._conn, self._has_vec, self._embedding_dim)

    def _try_load_vec(self) -> None:
        """Attempt to load sqlite-vec extension for ANN vector search."""
        try:
            import sqlite_vec  # type: ignore

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._has_vec = True
        except (ImportError, OSError):
            self._has_vec = False

    @property
    def has_vec(self) -> bool:
        return self._has_vec

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        for field in (
            "tags",
            "files_being_edited",
            "key_decisions",
            "open_questions",
            "next_steps",
            "active_errors",
        ):
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    d[field] = []
        return d

    # ── Memory CRUD ────────────────────────────────────────────────────

    def insert_memory(self, data: dict[str, Any]) -> int:
        """Insert a memory and return its ID."""
        params = self._build_insert_params(data)
        cursor = self._conn.execute(
            """INSERT INTO memories (
                content, embedding, tags, source, domain,
                directory_context, created_at, last_accessed,
                heat, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            params,
        )
        mem_id = cursor.lastrowid
        self._index_new_memory(mem_id, data)
        self._conn.commit()
        return mem_id

    @staticmethod
    def _build_insert_params(data: dict[str, Any]) -> tuple:
        """Extract insert parameters from a memory data dict."""
        now = datetime.now(timezone.utc).isoformat()
        return (
            data["content"],
            data.get("embedding"),
            json.dumps(data.get("tags", [])),
            data.get("source", ""),
            data.get("domain", ""),
            data.get("directory_context", ""),
            data.get("created_at", now),
            now,
            data.get("heat", 1.0),
            data.get("surprise_score", 0.0),
            data.get("importance", 0.5),
            data.get("emotional_valence", 0.0),
            data.get("confidence", 1.0),
            data.get("store_type", "episodic"),
            1 if data.get("is_protected", False) else 0,
            data.get("consolidation_stage", "labile"),
            data.get("theta_phase_at_encoding", 0.0),
            data.get("encoding_strength", 1.0),
            data.get("separation_index", 0.0),
            data.get("interference_score", 0.0),
            data.get("schema_match_score", 0.0),
            data.get("schema_id"),
            data.get("hippocampal_dependency", 1.0),
        )

    def _index_new_memory(self, mem_id: int, data: dict[str, Any]) -> None:
        """Add FTS5 and vector index entries for a new memory."""
        self._conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
            (mem_id, data["content"]),
        )
        embedding = data.get("embedding")
        if embedding and self._has_vec:
            self.insert_vector(mem_id, embedding)

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        self._conn.execute(
            "UPDATE memories SET heat = ? WHERE id = ?",
            (heat, memory_id),
        )
        self._conn.commit()

    def update_memory_importance(self, memory_id: int, importance: float) -> None:
        self._conn.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (importance, memory_id),
        )
        self._conn.commit()

    def update_memory_access(self, memory_id: int) -> None:
        now = self._now_iso()
        self._conn.execute(
            "UPDATE memories SET last_accessed = ?, "
            "access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        self._conn.commit()

    def update_memory_metamemory(
        self,
        memory_id: int,
        access_count: int,
        useful_count: int,
        confidence: float,
    ) -> None:
        self._conn.execute(
            "UPDATE memories SET access_count = ?, useful_count = ?, "
            "confidence = ? WHERE id = ?",
            (access_count, useful_count, confidence, memory_id),
        )
        self._conn.commit()

    def delete_memory(self, memory_id: int) -> bool:
        self._conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        if self._has_vec:
            try:
                self.delete_vector(memory_id)
            except Exception:
                pass
        cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def set_memory_protected(self, memory_id: int, protected: bool = True) -> None:
        self._conn.execute(
            "UPDATE memories SET is_protected = ? WHERE id = ?",
            (1 if protected else 0, memory_id),
        )
        self._conn.commit()

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        """Mark a memory as stale (or clear the stale flag)."""
        self._conn.execute(
            "UPDATE memories SET is_stale = ? WHERE id = ?",
            (1 if stale else 0, memory_id),
        )
        self._conn.commit()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()
