"""Memory query mixin for SqliteMemoryStore: filtered reads, time-window queries."""

from __future__ import annotations

import json
from typing import Any
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from mcp_server.observability import silent_failure


class SqliteQueryMixin:
    """Read-only memory queries on SQLite."""

    _conn: PsycopgCompatConnection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by SqliteMemoryStore."""
        return dict(row)

    def get_memories_for_domain(
        self,
        domain: str,
        min_heat: float = 0.05,
        limit: int = 50,
        heads_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Mirror of PgQueryMixin.get_memories_for_domain — heads_only routes
        through the current_memories view (supersession chain heads only).
        """
        src = "current_memories" if heads_only else "memories"
        rows = self._conn.execute(
            f"SELECT * FROM {src} WHERE (domain = ? OR is_global = 1) "
            "AND heat_base >= ? ORDER BY heat_base DESC LIMIT ?",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE (directory_context = ? OR is_global = 1) "
            "AND heat_base >= ? ORDER BY heat_base DESC",
            (directory, min_heat),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_hot_memories(
        self,
        min_heat: float = 0.7,
        limit: int = 20,
        include_benchmarks: bool = False,
        heads_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Mirror of PgQueryMixin.get_hot_memories — heads_only routes
        through the current_memories view (supersession chain heads only).
        """
        src = "current_memories" if heads_only else "memories"
        if include_benchmarks:
            rows = self._conn.execute(
                f"SELECT * FROM {src} WHERE heat_base >= ? ORDER BY heat_base DESC LIMIT ?",
                (min_heat, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT * FROM {src} WHERE heat_base >= ? "
                "AND NOT COALESCE(is_benchmark, 0) "
                "ORDER BY heat_base DESC LIMIT ?",
                (min_heat, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        """Return memories that have embeddings in the vec table."""
        rows = self._conn.execute("SELECT id, heat_base FROM memories").fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # Try to fetch embedding from vec table
            try:
                vec_row = self._conn.execute(
                    "SELECT embedding FROM memories_vec WHERE rowid = ?",
                    (d["id"],),
                ).fetchone()
                if vec_row and vec_row["embedding"] is not None:
                    d["embedding"] = bytes(vec_row["embedding"])
                    results.append(d)
            except Exception:
                continue
        return results

    def get_all_memories_for_validation(
        self,
        limit: int = 1000,
        *,
        after_id: int = 0,
        include_stale: bool = False,
    ) -> list[dict[str, Any]]:
        """Page through memories for validation, ``id`` order (I6-D6).

        Mirrors PgQueryMixin.get_all_memories_for_validation — see there
        for the cursor/include_stale rationale.
        """
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE id > ? AND (NOT is_stale OR ?) "
            "ORDER BY id ASC LIMIT ?",
            (after_id, int(include_stale), limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_created_after(
        self, iso_timestamp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE created_at >= ? "
            "ORDER BY created_at ASC LIMIT ?",
            (iso_timestamp, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_in_time_window(
        self, center_time: str, window_minutes: int
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE "
            "ABS((julianday(created_at) - julianday(?)) * 1440) <= ?",
            (center_time, window_minutes),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_for_decay(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE NOT is_stale"
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def delete_memories_by_tag(self, tag: str, domain: str | None = None) -> int:
        """Delete memories with the given tag, optionally scoped to a domain.

        precondition: tag is a non-empty string; domain is None or a non-empty string.
        postcondition: returns the number of memory rows removed; rows removed
            iff their tags list contains tag AND (domain is None OR row.domain
            matches). domain=None preserves the legacy global-purge behavior.

        SQLite lacks jsonb operators — filter in Python then delete by ID.
        """
        if domain is None:
            rows = self._conn.execute("SELECT id, tags FROM memories").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, tags FROM memories WHERE domain = ?", (domain,)
            ).fetchall()
        ids_to_delete: list[int] = []
        for r in rows:
            try:
                tags = (
                    json.loads(r["tags"]) if isinstance(r["tags"], str) else r["tags"]
                )
                if tag in tags:
                    ids_to_delete.append(r["id"])
            except (json.JSONDecodeError, TypeError):
                continue
        if not ids_to_delete:
            return 0
        placeholders = ",".join("?" * len(ids_to_delete))
        # Delete from FTS
        self._conn.execute(
            f"DELETE FROM memories_fts WHERE rowid IN ({placeholders})",
            ids_to_delete,
        )
        # Delete from vec (best effort)
        try:
            self._conn.execute(
                f"DELETE FROM memories_vec WHERE rowid IN ({placeholders})",
                ids_to_delete,
            )
        except Exception as exc:  # noqa: BLE001 — orphan vec rows must not block the purge
            silent_failure.note("sqlite_store.vec_index_delete", exc)
        # Delete from memories
        cur = self._conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            ids_to_delete,
        )
        self._conn.commit()
        return cur.rowcount
