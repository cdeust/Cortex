"""SQLite + FTS5 + sqlite-vec fallback memory store.

Drop-in replacement for PgMemoryStore when PostgreSQL is unavailable.
Mirrors the PG public API for every method the handlers/hooks call on
the shared store (119 shared methods; 16 PG-only remain — ingest
progress, decay iteration, procedural skills, tag-vector search — measured
2026-07-22 via an inspect.getmembers diff of the two classes; the prior
"all 89 methods" claim here was stale).

WRRF fusion and spread activation are computed client-side
(vs server-side PL/pgSQL in the PG backend).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from mcp_server.shared.temporal_normalize import normalize_date_to_iso
from mcp_server.infrastructure.sqlite_compat import (
    PsycopgCompatConnection,
    SqliteConnectionLike,
)
from mcp_server.infrastructure.sqlite_connection_registry import (
    SqliteConnectionRegistry,
    ThreadLocalSqliteConnection,
)
from mcp_server.infrastructure.sqlite_schema import (
    COLUMN_BACKFILLS,
    CURRENT_MEMORIES_VIEW_DDL,
    MEMORIES_FTS_DDL,
    MEMORIES_VEC_DDL,
    MIGRATIONS,
    get_all_ddl,
)
from mcp_server.infrastructure.sqlite_store_auxiliary import SqliteAuxiliaryMixin
from mcp_server.infrastructure.sqlite_store_entities import SqliteEntityMixin
from mcp_server.infrastructure.sqlite_store_entity_merge import (
    SqliteEntityMergeMixin,
)
from mcp_server.infrastructure.sqlite_store_grooming import SqliteGroomingMixin
from mcp_server.infrastructure.sqlite_store_mood import SqliteMoodMixin
from mcp_server.infrastructure.sqlite_store_queries import SqliteQueryMixin
from mcp_server.infrastructure.sqlite_store_receipts import SqliteReceiptsMixin
from mcp_server.infrastructure.sqlite_store_relationships import (
    SqliteRelationshipMixin,
)
from mcp_server.infrastructure.sqlite_store_rules import SqliteRuleMixin
from mcp_server.infrastructure.sqlite_store_search import SqliteSearchMixin
from mcp_server.infrastructure.sqlite_store_stats import SqliteStatsMixin
from mcp_server.observability import silent_failure
from mcp_server.shared.code_tokenize import augment_content
from mcp_server.infrastructure.embedding_engine import current_embedding_mode

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fts_augment(content: str) -> str:
    """Append identifier sub-tokens to FTS content (code-aware, issue #169)."""

    return augment_content(content or "")


_json_codec_registered = False


def _register_json_codec() -> None:
    """Make the wiki schema's `JSON` columns behave like PostgreSQL's.

    Two halves of one contract (issue #206):

    * READ — a converter bound to the `JSON` decltype, so `entity_ids` comes
      back a `list[int]` like psycopg's `INTEGER[]` rather than the string
      "[1,2]". Call sites iterate these (wiki_emerge.py:220); a raw string
      would iterate character-wise and yield garbage ids without raising.
    * WRITE — adapters so a handler can pass a Python `list`/`dict` straight
      through as psycopg allows. sqlite3 raises InterfaceError on those types
      by default, so nothing existing depends on the old behaviour.

    Only the `JSON` decltype is affected; every pre-existing column is
    declared INTEGER/TEXT/REAL and no converter is registered for those. No
    column anywhere declares `date`/`timestamp`, so sqlite3's built-in
    converters for those (the one behaviour PARSE_DECLTYPES turns on for
    free) cannot fire either. Verified 2026-07-27.
    """
    global _json_codec_registered
    if _json_codec_registered:
        return
    sqlite3.register_converter("JSON", json.loads)
    sqlite3.register_adapter(list, json.dumps)
    sqlite3.register_adapter(dict, json.dumps)
    _json_codec_registered = True


# Parity with PgMemoryStore's supersede_atomic operational bounds (engineering,
# not algorithmic). Bounded optimistic-concurrency rebase retry; defensive
# recursion cap on the acyclic chain walk.
_SUPERSEDE_REBASE_ATTEMPTS = 5
_CHAIN_HEAD_MAX_DEPTH = 100_000


class SqliteMemoryStore(
    SqliteEntityMixin,
    SqliteEntityMergeMixin,
    SqliteRelationshipMixin,
    SqliteQueryMixin,
    SqliteReceiptsMixin,
    SqliteRuleMixin,
    SqliteStatsMixin,
    SqliteGroomingMixin,
    SqliteAuxiliaryMixin,
    SqliteMoodMixin,
    SqliteSearchMixin,
):
    """SQLite + FTS5 + sqlite-vec storage engine for Cortex memory system."""

    _raw_conn: SqliteConnectionLike

    def __init__(self, db_path: str = "", embedding_dim: int = 384) -> None:
        self._embedding_dim = embedding_dim
        self._has_vec = False
        path = db_path or ":memory:"
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        _register_json_codec()
        self._connection_registry = SqliteConnectionRegistry(path)
        self._raw_conn = ThreadLocalSqliteConnection(self._connection_registry)
        self._conn = PsycopgCompatConnection(self._raw_conn)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create all tables, indexes, virtual tables, then migrate.

        Each statement runs independently — one failure doesn't
        prevent the rest from being created.
        """
        for ddl in get_all_ddl():
            try:
                self._conn.execute(ddl)
            except sqlite3.Error as exc:
                # Expected when an optional capability is absent (e.g. the
                # sqlite-vec extension); the remaining DDL still runs.
                logger.debug("DDL statement skipped: %s", exc)
        self._run_migrations()
        # After migrations: older databases only gain superseded_by_id via
        # MIGRATIONS, and the current_memories view references that column.
        self._conn.execute(CURRENT_MEMORIES_VIEW_DDL)
        self._conn.commit()
        self._try_load_vec()

    def _run_migrations(self) -> None:
        """Add columns that may be missing from older databases."""
        self._migrate_heat_to_heat_base()
        self._migrate_homeostatic_state_write_class()
        for table, column, col_def in MIGRATIONS:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            except sqlite3.OperationalError:
                # Column already present (or its table is absent): either way
                # this is not the migration that creates it, so the backfill
                # below must NOT run — it would overwrite values the write
                # path has since recorded.
                continue
            backfill = COLUMN_BACKFILLS.get((table, column))
            if backfill is not None:
                self._conn.execute(backfill)
        self._migrate_fts_code_tokenize()

    def _migrate_fts_code_tokenize(self) -> None:
        """One-shot: convert an external-content memories_fts to a self-content
        table and reindex every memory with code-aware sub-tokens (issue #169).

        Idempotent: a fresh DB (or an already-converted one) has no
        ``content=`` option in its ``memories_fts`` DDL, so this is a no-op.
        Only a legacy external-content table triggers the rebuild — required
        because appended sub-tokens cannot be safely deleted from an
        external-content index (see sqlite_schema.MEMORIES_FTS_DDL note).
        """
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'memories_fts'"
        ).fetchone()
        sql = (row["sql"] if row else None) or ""
        if "content=" not in sql:
            return  # already self-content (fresh DB or prior migration)

        self._conn.execute("DROP TABLE IF EXISTS memories_fts")
        self._conn.execute(MEMORIES_FTS_DDL)
        rows = self._conn.execute("SELECT id, content FROM memories").fetchall()
        for r in rows:
            self._conn.execute(
                "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
                (r["id"], augment_content(r["content"] or "")),
            )

    def _migrate_homeostatic_state_write_class(self) -> None:
        """M-D3 (7.1): rebuild homeostatic_state with PK (domain, write_class).

        SQLite cannot ALTER a PRIMARY KEY in place. Idempotent: only runs
        when the legacy single-column-PK table still exists (detected via
        absence of the ``write_class`` column — a fresh DB already has it
        from ``HOMEOSTATIC_STATE_DDL`` and this is a no-op). Same one-shot,
        no-read-shim policy as the PG migration (pg_schema.py): legacy rows
        are relabeled write_class='auto', the honest label given the
        pre-stratification factor was driven by a 92%-auto-capture corpus.
        """
        try:
            cols = self._conn.execute(
                "SELECT name FROM pragma_table_info('homeostatic_state')"
            ).fetchall()
        except sqlite3.OperationalError:
            return  # no table yet — DDL above will create it with write_class
        names: set[str] = set()
        for row in cols:
            try:
                names.add(row["name"])
            except (TypeError, KeyError, IndexError):
                try:
                    names.add(row[0])
                except (TypeError, IndexError):
                    pass
        if not names or "write_class" in names:
            return  # no legacy table, or already migrated
        try:
            self._conn.execute(
                "ALTER TABLE homeostatic_state RENAME TO homeostatic_state_legacy"
            )
            self._conn.execute(
                "CREATE TABLE homeostatic_state ("
                "  domain TEXT NOT NULL,"
                "  write_class TEXT NOT NULL DEFAULT 'auto'"
                "    CHECK (write_class IN "
                "('auto','deliberate','derived','mechanical')),"
                "  factor REAL NOT NULL DEFAULT 1.0 "
                "CHECK (factor > 0.0 AND factor < 10.0),"
                "  updated_at TEXT NOT NULL DEFAULT (datetime('now')),"
                "  PRIMARY KEY (domain, write_class)"
                ")"
            )
            self._conn.execute(
                "INSERT INTO homeostatic_state "
                "(domain, write_class, factor, updated_at) "
                "SELECT domain, 'auto', factor, updated_at "
                "FROM homeostatic_state_legacy"
            )
            self._conn.execute("DROP TABLE homeostatic_state_legacy")
        except sqlite3.OperationalError:
            pass

    def _migrate_heat_to_heat_base(self) -> None:
        """Phase 3 A3 migration (SQLite parity): rename heat → heat_base,
        add heat_base_set_at + no_decay. Idempotent: only runs when the
        legacy heat column still exists AND heat_base does not.

        SQLite supports ALTER TABLE ... RENAME COLUMN since 3.25 (2018);
        all supported platforms ship well above that.
        """
        try:
            cols = self._conn.execute(
                "SELECT name FROM pragma_table_info('memories')"
            ).fetchall()
            names: set[str] = set()
            for row in cols:
                # Row can be sqlite3.Row (keyed), dict, or tuple — normalize.
                try:
                    names.add(row["name"])
                except (TypeError, KeyError, IndexError):
                    try:
                        names.add(row[0])
                    except (TypeError, IndexError):
                        pass
        except sqlite3.OperationalError:
            return  # no memories table yet — new DB, DDL will create it with heat_base

        if "heat_base" not in names and "heat" in names:
            try:
                self._conn.execute(
                    "ALTER TABLE memories RENAME COLUMN heat TO heat_base"
                )
            except sqlite3.OperationalError:
                pass
        if "heat_base_set_at" not in names:
            # SQLite rejects ALTER TABLE ADD COLUMN with non-constant
            # defaults (e.g. datetime('now')). Add with empty default,
            # then UPDATE to set the timestamp from existing anchors.
            try:
                self._conn.execute(
                    "ALTER TABLE memories ADD COLUMN heat_base_set_at TEXT "
                    "NOT NULL DEFAULT ''"
                )
                self._conn.execute(
                    "UPDATE memories SET heat_base_set_at = "
                    "COALESCE(last_accessed, created_at, datetime('now'))"
                )
            except sqlite3.OperationalError:
                pass
        if "no_decay" not in names:
            try:
                self._conn.execute(
                    "ALTER TABLE memories ADD COLUMN no_decay "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass

    def _try_load_vec(self) -> None:
        """Attempt to load sqlite-vec extension and create vec table."""
        try:
            import sqlite_vec  # noqa: PLC0415, F401 — optional dependency ([sqlite] extra); imported where used so environments without it keep working

            self._connection_registry.enable_vector_extension(sqlite_vec.load)
            self._conn.execute(MEMORIES_VEC_DDL)
            self._conn.commit()
            self._has_vec = True
            logger.info("sqlite-vec loaded — vector search enabled")
        except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
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

    def _insert_memory_rows(self, data: dict[str, Any]) -> int:
        """Insert a memory into memories + FTS5 + vec tables — no commit.

        The caller owns the transaction boundary: insert_memory() commits;
        supersede_atomic() commits or rolls back the row together with its
        supersession edge so a lost race never leaves a disconnected row.
        """
        now = _now_iso()
        # Parity with PgMemoryStore._build_insert_params, including the absence
        # of an "is it already ISO?" pre-test: normalize_date_to_iso owns that
        # decision and returns a real ISO datetime unchanged. The pre-test this
        # replaces was `"T" not in raw_created`, which skipped normalization
        # for every string merely CONTAINING a T — including
        # "8 May 2023 13:56 EST" (issue #252).
        raw_created = data.get("created_at")
        if raw_created and isinstance(raw_created, str):
            raw_created = normalize_date_to_iso(raw_created) or raw_created
        content = data["content"]
        # A3 decay clock parity with PgMemoryStore: anchor heat_base_set_at to
        # the event date (created_at), not NOW(), so historical-dated inserts
        # engage the SQL forgetting law. No-op for fresh writes. See
        # PgMemoryStore.insert_memory for the rationale.
        heat_base_anchor = data.get("heat_base_set_at") or raw_created or now
        cur = self._conn.execute(
            """INSERT INTO memories (
                content, tags, source, domain,
                directory_context, created_at, last_accessed, heat_base_set_at,
                heat_base, surprise_score, importance,
                emotional_valence, confidence, store_type,
                is_protected, consolidation_stage,
                theta_phase_at_encoding, encoding_strength,
                separation_index, interference_score,
                schema_match_score, schema_id,
                hippocampal_dependency, is_benchmark, agent_context,
                is_global, supersedes_id, source_attribution,
                stimulus_signature, extinction_strength, write_class,
                capture_origin
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                content,
                json.dumps(data.get("tags", [])),
                data.get("source", ""),
                data.get("domain", ""),
                data.get("directory_context", ""),
                raw_created or now,
                now,
                heat_base_anchor,
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
                data.get("supersedes_id"),
                data.get("source_attribution", "unknown"),
                data.get("stimulus_signature", ""),
                data.get("extinction_strength", 0.0),
                data.get("write_class", "deliberate"),
                # issue #365: channel-derived capture origin; "unknown" keeps
                # every existing writer's behaviour unchanged.
                data.get("capture_origin", "unknown"),
            ),
        )
        memory_id = cur.lastrowid
        if memory_id is None:
            # An INSERT always assigns a rowid; None means the statement did
            # not execute as an INSERT — a broken contract, not a data state.
            raise sqlite3.ProgrammingError("memory INSERT produced no lastrowid")
        self._conn.execute(
            "INSERT INTO memories_fts(rowid, content) VALUES (?, ?)",
            (memory_id, _fts_augment(content)),
        )
        embedding = data.get("embedding")
        if embedding is not None:
            # Stamp provenance whenever an embedding was PRODUCED, independent of
            # whether the vec0 store is present. The tag records which encoder
            # made this memory's embedding ('neural'/'fallback'), not whether it
            # was physically stored. Without this, a store built without the
            # sqlite-vec extension (``_has_vec`` False — e.g. an install missing
            # the [sqlite] extra) would leave embedding_model='' — a silent third
            # state that hides the fallback and starves the re-embed worklist
            # (issue #169, CI regression on the no-[sqlite] matrix legs).
            self._stamp_embedding_model(memory_id, data.get("embedding_model"))
            if self._has_vec:
                vec = self._bytes_to_vector(embedding)
                if vec is not None:
                    self._conn.execute(
                        "INSERT INTO memories_vec(rowid, embedding) VALUES (?, ?)",
                        (memory_id, vec.tobytes()),
                    )
        return memory_id

    def insert_memory(self, data: dict[str, Any]) -> int:
        """Insert a memory into memories + FTS5 + vec tables."""
        memory_id = self._insert_memory_rows(data)
        self._conn.commit()
        return memory_id

    def _current_chain_head(self, target_id: int) -> int | None:
        """Walk ``target_id``'s supersession chain to its open head.

        Follows forward ``superseded_by_id`` edges to the row whose
        superseded_by_id IS NULL. Returns that id, or None if the target no
        longer exists. Mirrors PgMemoryStore._current_chain_head.
        """
        row = self._conn.execute(
            """WITH RECURSIVE chain(id, superseded_by_id, hops) AS (
                   SELECT id, superseded_by_id, 0
                   FROM memories WHERE id = ?
                   UNION ALL
                   SELECT m.id, m.superseded_by_id, c.hops + 1
                   FROM memories m JOIN chain c ON m.id = c.superseded_by_id
                   WHERE c.hops < ?
               )
               SELECT id FROM chain
               WHERE superseded_by_id IS NULL
               ORDER BY hops DESC LIMIT 1""",
            (target_id, _CHAIN_HEAD_MAX_DEPTH),
        ).fetchone()
        return int(row["id"]) if row else None

    def supersede_atomic(
        self, data: dict[str, Any], target_id: int
    ) -> tuple[int | None, int | None]:
        """Insert ``data`` as the supersessor of ``target_id``'s head, atomically.

        SQLite parity for PgMemoryStore.supersede_atomic. One transaction on the
        current execution thread's connection inserts the new row
        (supersedes_id = the walked head) and stamps that head's
        ``superseded_by_id`` — a compare-and-set that lands only while the head
        is still open. On a lost CAS the transaction rolls back (the insert,
        its FTS and vec rows all undone — no orphan is ever committed) and we
        rebase onto the moved head, bounded by _SUPERSEDE_REBASE_ATTEMPTS.

        Returns ``(new_id, head_id)`` on success (``head_id`` == ``target_id``
        unless a race rebased us), ``(None, last_head_id)`` when the bounded
        rebase exhausts, or ``(None, None)`` when the target vanished.
        """
        last_head: int | None = None
        for _ in range(_SUPERSEDE_REBASE_ATTEMPTS):
            head_id = self._current_chain_head(target_id)
            if head_id is None:
                return None, None
            last_head = head_id
            data["supersedes_id"] = head_id
            try:
                new_id = self._insert_memory_rows(data)
                rowcount = self._conn.execute(
                    "UPDATE memories SET superseded_by_id = ? "
                    "WHERE id = ? AND superseded_by_id IS NULL",
                    (new_id, head_id),
                ).rowcount
            except Exception:
                self._conn.rollback()
                raise
            if rowcount != 1:
                self._conn.rollback()
                continue
            try:
                self._transfer_anchor(head_id, new_id)
            except Exception:
                self._conn.rollback()
                raise
            self._conn.commit()
            return new_id, head_id
        return None, last_head

    def _transfer_anchor(self, head_id: int, new_id: int) -> None:
        """Anchor follows the chain head at supersession (decision 2026-07-07).

        SQLite parity for PgMemoryStore._transfer_anchor_on — runs inside the
        supersede transaction, before commit. MAX() mirrors GREATEST/OR: the
        new row's own heat and no_decay are never lowered. The heat_base write
        is on the I2 canonical-writer allow-list
        (tests_py/invariants/test_I2_canonical_writer.py) — it cannot route
        through bump_heat_raw, which commits mid-transaction.
        """
        old = self._conn.execute(
            "SELECT no_decay, heat_base FROM memories "
            "WHERE id = ? AND is_protected = 1",
            (head_id,),
        ).fetchone()
        if old is None:
            return
        # heat_base first in the SET list so the I2 static scanner
        # (single-line "UPDATE memories SET heat_base") sees this writer.
        self._conn.execute(
            "UPDATE memories SET heat_base = MAX(heat_base, ?), "
            "is_protected = 1, no_decay = MAX(no_decay, ?), "
            "heat_base_set_at = CURRENT_TIMESTAMP WHERE id = ?",
            (old["heat_base"], 1 if old["no_decay"] else 0, new_id),
        )

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

    def get_homeostatic_factor(self, domain: str, write_class: str = "auto") -> float:
        """SQLite parity: default 1.0 when no row exists.

        M-D3 (7.1): ``write_class`` defaults to ``"auto"`` — see
        ``pg_store.py::get_homeostatic_factor`` for the full rationale.
        """
        row = self._conn.execute(
            "SELECT COALESCE(MAX(factor), 1.0) AS factor "
            "FROM homeostatic_state WHERE domain = ? AND write_class = ?",
            (domain or "", write_class),
        ).fetchone()
        if row is None:
            return 1.0
        try:
            return float(row["factor"])
        except (KeyError, TypeError, IndexError):
            return 1.0

    def set_homeostatic_factor(
        self, domain: str, factor: float, write_class: str = "auto"
    ) -> None:
        """SQLite parity UPSERT on homeostatic_state (M-D3: PK includes
        write_class — see ``pg_store.py::set_homeostatic_factor``)."""
        clamped = max(0.01, min(9.99, float(factor)))
        self._conn.execute(
            "INSERT INTO homeostatic_state (domain, write_class, factor, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(domain, write_class) DO UPDATE "
            "SET factor = excluded.factor, updated_at = CURRENT_TIMESTAMP",
            (domain or "", write_class, clamped),
        )
        self._conn.commit()

    def log_homeostatic_fold(
        self, domain: str, write_class: str, factor: float, rows_folded: int
    ) -> int:
        """SQLite parity fold-event journal (M-D3, 7.1) — see
        ``pg_store.py::log_homeostatic_fold``."""
        cur = self._conn.execute(
            "INSERT INTO homeostatic_fold_log "
            "(domain, write_class, factor, rows_folded) VALUES (?, ?, ?, ?)",
            (domain or "", write_class, float(factor), int(rows_folded)),
        )
        self._conn.commit()
        return cur.lastrowid or 0

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

    def update_memory_value(self, memory_id: int, value: float) -> None:
        """Persist a memory's learned RL value (B2). Defensive on stores whose
        `value` column predates this migration."""
        try:
            self._conn.execute(
                "UPDATE memories SET value = ? WHERE id = ?",
                (value, memory_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            # `value` column absent (pre-migration store) — documented no-op.
            pass

    def update_memory_extinction(
        self, memory_id: int, extinction_strength: float
    ) -> None:
        """Persist a memory's reversible inhibitory extinction tag (E2).

        Writes ONLY the ``extinction_strength`` scalar in [0,1]; the memory's
        content and heat_base are left untouched — extinction suppresses the
        effective retrieval weight without erasing the trace, so decaying
        (spontaneous recovery) or clearing (reinstatement) the tag restores the
        original association (Bouton 2004). Defensive on stores whose
        ``extinction_strength`` column predates this migration — a failed UPDATE
        is swallowed so deprecation never breaks on an un-migrated store."""
        try:
            e = max(0.0, min(1.0, float(extinction_strength)))
            self._conn.execute(
                "UPDATE memories SET extinction_strength = ? WHERE id = ?",
                (e, memory_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            # `extinction_strength` column absent (pre-migration store) —
            # documented no-op per the docstring above.
            pass

    # ── Connection acquisition (PgMemoryStore parity) ─────────────────
    #
    # PgMemoryStore splits connections across an interactive pool and a batch
    # pool so long-running jobs cannot starve the hot path. SQLite instead
    # binds each transaction to its execution thread's persistent connection;
    # both accessors expose the same stable facade, which resolves that native
    # connection at every call.
    #
    # These exist so handlers stay backend-agnostic: anchor.py, get_rules.py,
    # the codebase_analyze/backfill/consolidation writers all call
    # `store.acquire_*()` unconditionally. Without them a SQLite-backed
    # install raised AttributeError — an LSP break, not a missing feature,
    # since the handler cannot know which store it was handed (issue #220).

    @contextmanager
    def acquire_interactive(self) -> Iterator[PsycopgCompatConnection]:
        """Yield the store's connection for a short-lived hot-path operation."""
        yield self._conn

    @contextmanager
    def acquire_batch(self) -> Iterator[PsycopgCompatConnection]:
        """Yield the store's connection for long-running batch work."""
        yield self._conn

    def _execute(self, query: str, params: Any = None) -> Any:
        """PgMemoryStore-parity passthrough to the translating connection.

        PG-flavored SQL a caller sends here (``%s`` placeholders, ``NOW()``,
        ``= ANY(...)``) is translated by ``PsycopgCompatConnection``; a
        construct SQLite cannot express (e.g. ``@>`` jsonb containment)
        raises ``sqlite3.OperationalError``, which the callers' documented
        mechanism boundaries treat as the degraded mode — previously the
        same sites raised ``AttributeError`` before the query even ran
        (issue #220).
        """
        return self._conn.execute(query, params)

    def search_newer_neighbors(
        self,
        query_embedding: bytes,
        after: str,
        exclude_id: int,
        top_k: int = 10,
    ) -> list[tuple[float, float]]:
        """Vector neighbors created strictly after ``after``, nearest first.

        PgMemoryStore parity (see ``pg_store.py::search_newer_neighbors``):
        returns ``(similarity, age_hours)`` per newer neighbor. SQLite has no
        ``<=>`` operator, so the candidate rows are scored with the same
        numpy cosine the fallback vector search uses.
        """
        if not self._has_vec:
            # Without sqlite-vec no vectors are persisted at all, so there is
            # no interference signal to compute — same empty result the PG
            # query yields for a corpus with NULL embeddings.
            return []
        query_vec = self._bytes_to_vector(query_embedding)
        if query_vec is None:
            return []
        q_norm = float(np.linalg.norm(query_vec))
        if q_norm == 0.0:
            return []
        # Embeddings live in the memories_vec virtual table; join client-side
        # per the established idiom (sqlite_store_search.get_hot_embeddings):
        # fetch candidate rows, then the vector per rowid.
        rows = self._conn.execute(
            "SELECT id, created_at FROM memories "
            "WHERE created_at > ? AND id != ? AND is_stale = 0",
            (after, exclude_id),
        ).fetchall()
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, float]] = []
        for r in rows:
            vec_row = self._conn.execute(
                "SELECT embedding FROM memories_vec WHERE rowid = ?",
                (int(r["id"]),),
            ).fetchone()
            if vec_row is None:
                continue
            vec = self._bytes_to_vector(vec_row["embedding"])
            if vec is None or vec.shape != query_vec.shape:
                continue
            denom = q_norm * float(np.linalg.norm(vec))
            if denom == 0.0:
                continue
            similarity = float(np.dot(query_vec, vec)) / denom
            try:
                created = datetime.fromisoformat(str(r["created_at"]))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_hours = (now - created).total_seconds() / 3600.0
            except ValueError:
                age_hours = float("inf")
            scored.append((similarity, age_hours))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]

    def update_forgetting_pressure_accum(self, memory_id: int, accum: float) -> None:
        """Persist the permanent-circuit leaky-integrator state for one memory.

        PgMemoryStore parity — see ``pg_store.py`` for the rationale
        (source: mcp_server/core/active_forgetting.py, update_pressure_accum).
        """
        self._conn.execute(
            "UPDATE memories SET forgetting_pressure_accum = ? WHERE id = ?",
            (accum, memory_id),
        )
        self._conn.commit()

    def _stamp_embedding_model(self, memory_id: int, model: str | None) -> None:
        """Record which vector space a memory's embedding lives in (issue #169).

        precondition: ``memory_id`` refers to a just-written vec row.
        postcondition: ``memories.embedding_model`` is set to ``model`` when
        given, else to the process-wide engine mode
        (``current_embedding_mode``). This is the single tag the vector search
        reads to keep 'neural' and 'fallback' vectors — incompatible geometries
        — from cross-ranking. Best-effort: a missing column (pre-migration DB in
        a race) is swallowed, same discipline as the vec insert it accompanies.
        """
        if not model:
            model = current_embedding_mode()
        # 'unknown' means no engine was constructed (e.g. a direct store test
        # that inserts a raw vector); leave the column at its '' default rather
        # than writing a misleading tag.
        if model == "unknown":
            return
        try:
            self._conn.execute(
                "UPDATE memories SET embedding_model = ? WHERE id = ?",
                (model, memory_id),
            )
        except sqlite3.OperationalError:
            pass

    def select_fallback_embeddings(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return current memories whose vector was written in fallback mode.

        precondition: ``limit`` > 0.
        postcondition: returns up to ``limit`` ``{memory_id, content}`` dicts for
        non-superseded memories tagged ``embedding_model='fallback'``, hottest
        first — the re-embedding worklist that upgrades a store transparently
        once the neural model becomes available (issue #169). Empty when the
        column is absent or nothing is tagged fallback.
        """
        try:
            rows = self._conn.execute(
                "SELECT id, content FROM current_memories "
                "WHERE embedding_model = 'fallback' "
                "ORDER BY heat_base DESC LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [{"memory_id": r["id"], "content": r["content"]} for r in rows]

    def reembed_memory(self, memory_id: int, embedding: bytes | None) -> None:
        """Replace a memory's stored vector and restamp its provider (issue #169).

        precondition: ``embedding`` was produced by the current process encoder.
        postcondition: the vec row is replaced (when the vec store is present)
        and ``embedding_model`` is restamped to the current mode — so a
        fallback-tagged memory becomes 'neural' once the model is available,
        without touching content or the compression flags. No-op for a None
        embedding. Commits.
        """
        if embedding is None:
            return
        if self._has_vec:
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
                except Exception as exc:  # noqa: BLE001 — row keeps its old vector on failure
                    silent_failure.note("sqlite_store.vec_index_update", exc)
        self._stamp_embedding_model(memory_id, None)
        self._conn.commit()

    def delete_memory(self, memory_id: int) -> bool:
        self._conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
        if self._has_vec:
            try:
                self._conn.execute(
                    "DELETE FROM memories_vec WHERE rowid = ?", (memory_id,)
                )
            except Exception as exc:  # noqa: BLE001 — an orphan vec row must not block deletion
                silent_failure.note("sqlite_store.vec_index_delete", exc)
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

    def set_source_attribution(self, memory_id: int, attribution: str) -> None:
        """Persist a provenance grade (I6-D6). Sole intended writer:
        handlers/validate_memory.py — see core/provenance.py for the
        verified/verifiable/unverifiable vocabulary this column now holds."""
        self._conn.execute(
            "UPDATE memories SET source_attribution = ? WHERE id = ?",
            (attribution, memory_id),
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
            (memory_id, _fts_augment(content)),
        )
        # Re-embed restamps the vector's space: a compression/replay re-encode
        # under the current engine upgrades a prior 'fallback' row to 'neural'
        # transparently (issue #169). Stamp whenever an embedding was produced,
        # even without the vec store present (see _insert_memory_rows).
        if embedding is not None:
            self._stamp_embedding_model(memory_id, None)
            if self._has_vec:
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
                    except Exception as exc:  # noqa: BLE001 — row keeps its old vector on failure
                        silent_failure.note("sqlite_store.vec_index_update", exc)
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
