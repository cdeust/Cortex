"""SQLite + FTS5 + sqlite-vec fallback memory store.

Drop-in replacement for PgMemoryStore when PostgreSQL is unavailable.
Uses the same public API — all 89 methods with identical signatures.

WRRF fusion and spread activation are computed client-side
(vs server-side PL/pgSQL in the PG backend).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.infrastructure.sqlite_schema import (
    MEMORIES_VEC_DDL,
    MIGRATIONS,
    get_all_ddl,
)
from mcp_server.infrastructure.sqlite_store_auxiliary import SqliteAuxiliaryMixin
from mcp_server.infrastructure.sqlite_store_entities import SqliteEntityMixin
from mcp_server.infrastructure.sqlite_store_queries import SqliteQueryMixin
from mcp_server.infrastructure.sqlite_store_relationships import (
    SqliteRelationshipMixin,
)
from mcp_server.infrastructure.sqlite_store_rules import SqliteRuleMixin
from mcp_server.infrastructure.sqlite_store_search import SqliteSearchMixin
from mcp_server.infrastructure.sqlite_store_stats import SqliteStatsMixin

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteMemoryStore(
    SqliteEntityMixin,
    SqliteRelationshipMixin,
    SqliteQueryMixin,
    SqliteRuleMixin,
    SqliteStatsMixin,
    SqliteAuxiliaryMixin,
    SqliteSearchMixin,
):
    """SQLite + FTS5 + sqlite-vec storage engine for Cortex memory system."""

    def __init__(self, db_path: str = "", embedding_dim: int = 384) -> None:
        self._embedding_dim = embedding_dim
        self._has_vec = False
        path = db_path or ":memory:"
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA foreign_keys=ON")
        self._raw_conn = raw
        self._conn = PsycopgCompatConnection(raw)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create all tables, indexes, virtual tables, then migrate.

        Each statement runs independently — one failure doesn't
        prevent the rest from being created.
        """
        for ddl in get_all_ddl():
            try:
                self._conn.execute(ddl)
            except Exception:
                pass
        self._run_migrations()
        self._conn.commit()
        self._try_load_vec()

    def _run_migrations(self) -> None:
        """Add columns that may be missing from older databases."""
        for table, column, col_def in MIGRATIONS:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            except sqlite3.OperationalError:
                pass

    def _try_load_vec(self) -> None:
        """Attempt to load sqlite-vec extension and create vec table."""
        try:
            import sqlite_vec  # noqa: F401

            self._raw_conn.enable_load_extension(True)
            sqlite_vec.load(self._raw_conn)
            self._raw_conn.enable_load_extension(False)
            self._conn.execute(MEMORIES_VEC_DDL)
            self._conn.commit()
            self._has_vec = True
            logger.info("sqlite-vec loaded — vector search enabled")
        except Exception as exc:
            logger.info("sqlite-vec unavailable (%s) — vector search disabled", exc)
            self._has_vec = False

    @property
    def has_vec(self) -> bool:
        return self._has_vec

    @staticmethod
    def _now_iso() -> str:
        return _now_iso()

    # ── Embedding conversion ──────────────────────────────────────────

    @staticmethod
    def _bytes_to_vector(emb: bytes | None) -> np.ndarray | None:
        if emb is None:
            return None
        return np.frombuffer(emb, dtype=np.float32).copy()

    @staticmethod
    def _vector_to_bytes(vec: Any) -> bytes | None:
        if vec is None:
            return None
        return np.asarray(vec, dtype=np.float32).tobytes()

    # ── Memory CRUD ───────────────────────────────────────────────────

    def insert_memory(self, data: dict[str, Any]) -> int:
        """Insert a memory into memories + FTS5 + vec tables."""
        now = _now_iso()
        raw_created = data.get("created_at")
        if raw_created and isinstance(raw_created, str) and "T" not in raw_created:
            try:
                from mcp_server.core.temporal import normalize_date_to_iso

                raw_created = normalize_date_to_iso(raw_created) or raw_created
            except ImportError:
                pass
        content = data["content"]
        cur = self._conn.execute(
            """INSERT INTO memories (
                content, tags, source, domain,
                directory_context, created_at, last_accessed,
                heat_base, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency, is_benchmark, agent_context,
                is_global
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                content,
                json.dumps(data.get("tags", [])),
                data.get("source", ""),
                data.get("domain", ""),
                data.get("directory_context", ""),
                raw_created or now,
                now,
                data.get("heat", 1.0),
                data.get("surprise_score", 0.0),
                data.get("importance", 0.5),
                data.get("emotional_valence", 0.0),
                data.get("confidence", 1.0),
                data.get("store_type", "episodic"),
                int(data.get("is_protected", False)),
                data.get("consolidation_stage", "labile"),
                data.get("theta_phase_at_encoding", 0.0),
                data.get("encoding_strength", 1.0),
                data.get("separation_index", 0.0),
                data.get("interference_score", 0.0),
                data.get("schema_match_score", 0.0),
                data.get("schema_id"),
                data.get("hippocampal_dependency", 1.0),
                int(data.get("is_benchmark", False)),
                data.get("agent_context", ""),
                int(data.get("is_global", False)),
            ),
        )
        memory_id = cur.lastrowid
        self._conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
            (memory_id, content),
        )
        embedding = data.get("embedding")
        if self._has_vec and embedding is not None:
            vec = self._bytes_to_vector(embedding)
            if vec is not None:
                self._conn.execute(
                    "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                    (memory_id, vec.tobytes()),
                )
        self._conn.commit()
        return memory_id  # type: ignore[return-value]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        return self._normalize_memory_row(row)

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        """Canonical A3 single-row heat writer (SQLite parity).

        Delegates to ``bump_heat_raw`` which writes heat_base + stamps
        heat_base_set_at. Mirrors PgMemoryStore.update_memory_heat.
        Source: docs/program/phase-3-a3-migration-design.md §3.7.
        """
        self.bump_heat_raw(memory_id, heat)

    def bump_heat_raw(self, memory_id: int, new_heat_base: float) -> None:
        """A3 canonical writer on memories.heat_base (SQLite parity).

        Mirrors PgMemoryStore.bump_heat_raw. Defensive clamp to [0, 1].
        """
        clamped = max(0.0, min(1.0, float(new_heat_base)))
        self._conn.execute(
            "UPDATE memories SET heat_base = ?, heat_base_set_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (clamped, memory_id),
        )
        self._conn.commit()

    def get_homeostatic_factor(self, domain: str) -> float:
        """SQLite parity: default 1.0 when no row exists."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(factor), 1.0) AS factor "
            "FROM homeostatic_state WHERE domain = ?",
            (domain or "",),
        ).fetchone()
        if row is None:
            return 1.0
        try:
            return float(row["factor"] if hasattr(row, "__getitem__") else row[0])
        except (KeyError, TypeError, IndexError):
            return 1.0

    def set_homeostatic_factor(self, domain: str, factor: float) -> None:
        """SQLite parity UPSERT on homeostatic_state."""
        clamped = max(0.01, min(9.99, float(factor)))
        self._conn.execute(
            "INSERT INTO homeostatic_state (domain, factor, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(domain) DO UPDATE "
            "SET factor = excluded.factor, updated_at = CURRENT_TIMESTAMP",
            (domain or "", clamped),
        )
        self._conn.commit()

    def update_memories_heat_batch(self, updates: list[tuple[int, float]]) -> int:
        """A3 batch writer on heat_base (SQLite parity).

        ``executemany`` + single commit — SQLite has no array types so
        batching collapses per-row commits into a single transaction.
        Refreshes ``heat_base_set_at`` on every touched row so recall
        sees a fresh bump timestamp.
        Source: issue #13; docs/program/phase-3-a3-migration-design.md §3.8.
        """
        if not updates:
            return 0
        self._raw_conn.executemany(
            "UPDATE memories SET heat_base = ?, "
            "heat_base_set_at = CURRENT_TIMESTAMP WHERE id = ?",
            [(max(0.0, min(1.0, float(h))), int(i)) for i, h in updates],
        )
        self._conn.commit()
        return len(updates)

    def update_memory_importance(self, memory_id: int, importance: float) -> None:
        self._conn.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (importance, memory_id),
        )
        self._conn.commit()

    def update_memory_access(self, memory_id: int) -> None:
        self._conn.execute(
            "UPDATE memories SET last_accessed = datetime('now'), "
            "access_count = access_count + 1 WHERE id = ?",
            (memory_id,),
        )
        self._conn.commit()

    def update_memory_metamemory(
        self, memory_id: int, access_count: int, useful_count: int, confidence: float
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
                self._conn.execute(
                    "DELETE FROM memories_vec WHERE rowid = ?", (memory_id,)
                )
            except Exception:
                pass
        cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def set_memory_protected(self, memory_id: int, protected: bool = True) -> None:
        self._conn.execute(
            "UPDATE memories SET is_protected = ? WHERE id = ?",
            (int(protected), memory_id),
        )
        self._conn.commit()

    def mark_memory_stale(self, memory_id: int, stale: bool = True) -> None:
        self._conn.execute(
            "UPDATE memories SET is_stale = ? WHERE id = ?",
            (int(stale), memory_id),
        )
        self._conn.commit()

    # ── Compression ───────────────────────────────────────────────────

    def update_memory_compression(
        self,
        memory_id: int,
        content: str,
        embedding: bytes | None,
        compression_level: int,
        original_content: str | None = None,
    ) -> None:
        if original_content is not None:
            self._conn.execute(
                "UPDATE memories SET content = ?, "
                "compression_level = ?, compressed = 1, original_content = ? "
                "WHERE id = ?",
                (content, compression_level, original_content, memory_id),
            )
        else:
            self._conn.execute(
                "UPDATE memories SET content = ?, "
                "compression_level = ?, compressed = 1 WHERE id = ?",
                (content, compression_level, memory_id),
            )
        # Update FTS
        self._conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        self._conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
            (memory_id, content),
        )
        # Update vec
        if self._has_vec and embedding is not None:
            vec = self._bytes_to_vector(embedding)
            if vec is not None:
                try:
                    self._conn.execute(
                        "DELETE FROM memories_vec WHERE rowid = ?", (memory_id,)
                    )
                    self._conn.execute(
                        "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                        (memory_id, vec.tobytes()),
                    )
                except Exception:
                    pass
        self._conn.commit()

    # ── Row normalization ─────────────────────────────────────────────

    def _normalize_memory_row(self, row: dict | sqlite3.Row) -> dict[str, Any]:
        """Normalize a memory row for consistent API output.

        A3: expose heat_base as heat for Python callers that expect
        the pre-A3 dict key.
        """
        d = dict(row)
        if "heat" not in d and "heat_base" in d:
            d["heat"] = d["heat_base"]
        if isinstance(d.get("tags"), str):
            try:
                d["tags"] = json.loads(d["tags"])
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
        for field in (
            "files_being_edited",
            "key_decisions",
            "open_questions",
            "next_steps",
            "active_errors",
            "entity_signature",
            "relationship_types",
            "tag_signature",
        ):
            if isinstance(d.get(field), str):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        for field in (
            "is_protected",
            "is_stale",
            "compressed",
            "is_benchmark",
            "is_global",
            "is_active",
            "is_causal",
            "archived",
        ):
            if field in d and isinstance(d[field], int):
                d[field] = bool(d[field])
        return d

    # ── Lifecycle ─────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()
