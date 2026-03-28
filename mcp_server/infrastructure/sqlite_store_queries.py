"""Memory query mixin for SqliteMemoryStore: filtered reads, time-window queries."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class SqliteQueryMixin:
    """Read-only memory queries on SQLite."""

    _conn: sqlite3.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by SqliteMemoryStore."""
        return dict(row)

    def get_memories_for_domain(
        self, domain: str, min_heat: float = 0.05, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE domain = ? AND heat >= ? "
            "ORDER BY heat DESC LIMIT ?",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE directory_context = ? "
            "AND heat >= ? ORDER BY heat DESC",
            (directory, min_heat),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_hot_memories(
        self,
        min_heat: float = 0.7,
        limit: int = 20,
        include_benchmarks: bool = False,
    ) -> list[dict[str, Any]]:
        if include_benchmarks:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE heat >= ? ORDER BY heat DESC LIMIT ?",
                (min_heat, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE heat >= ? "
                "AND NOT COALESCE(is_benchmark, 0) "
                "ORDER BY heat DESC LIMIT ?",
                (min_heat, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        """Return memories that have embeddings in the vec table."""
        rows = self._conn.execute("SELECT id, heat FROM memories").fetchall()
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
        self, limit: int = 1000
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE NOT is_stale "
            "ORDER BY last_accessed ASC LIMIT ?",
            (limit,),
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

    def delete_memories_by_tag(self, tag: str) -> int:
        """Delete all memories containing the given tag.

        SQLite lacks jsonb operators — filter in Python then delete by ID.
        """
        rows = self._conn.execute("SELECT id, tags FROM memories").fetchall()
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
        except Exception:
            pass
        # Delete from memories
        cur = self._conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            ids_to_delete,
        )
        self._conn.commit()
        return cur.rowcount
