"""Memory query mixin: filtered reads, time-window queries, tag operations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class MemoryQueryMixin:
    """Read-only memory queries beyond basic CRUD.

    Requires _conn (sqlite3.Connection) and _row_to_dict on the host class.
    """

    _conn: sqlite3.Connection

    def get_memories_for_domain(
        self, domain: str, min_heat: float = 0.05, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE domain = ? AND heat >= ? "
            "ORDER BY heat DESC LIMIT ?",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE directory_context = ? "
            "AND heat >= ? ORDER BY heat DESC",
            (directory, min_heat),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_hot_memories(
        self, min_heat: float = 0.7, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE heat >= ? ORDER BY heat DESC LIMIT ?",
            (min_heat, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, heat, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_memories_for_validation(
        self, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Fetch non-stale memories, oldest-accessed first."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE is_stale = 0 "
            "ORDER BY last_accessed ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_memories_created_after(
        self, iso_timestamp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Fetch memories created after a given ISO timestamp."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE created_at >= ? "
            "ORDER BY created_at ASC LIMIT ?",
            (iso_timestamp, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_memories_in_time_window(
        self, center_time: str, window_minutes: int
    ) -> list[dict[str, Any]]:
        """Get memories within +/- window_minutes of center_time."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE "
            "abs(julianday(created_at) - julianday(?)) * 1440 <= ?",
            (center_time, window_minutes),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_all_memories_for_decay(self) -> list[dict[str, Any]]:
        """Get all non-stale memories for decay/compression cycles."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE is_stale = 0"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete_memories_by_tag(self, tag: str) -> int:
        """Hard-delete all memories containing the given tag."""
        rows = self._conn.execute(
            "SELECT id, tags FROM memories WHERE is_stale = 0"
        ).fetchall()
        to_delete = []
        for row in rows:
            raw_tags = row["tags"] or "[]"
            try:
                tags = json.loads(raw_tags)
            except Exception:
                tags = []
            if tag in tags:
                to_delete.append(row["id"])

        for mid in to_delete:
            self._conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
        if to_delete:
            self._conn.commit()
        return len(to_delete)
