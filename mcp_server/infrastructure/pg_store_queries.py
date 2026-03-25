"""Memory query mixin for PgMemoryStore: filtered reads, time-window queries."""

from __future__ import annotations

import json
from typing import Any

import psycopg


class PgQueryMixin:
    """Read-only memory queries on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    def get_memories_for_domain(
        self, domain: str, min_heat: float = 0.05, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE domain = %s AND heat >= %s "
            "ORDER BY heat DESC LIMIT %s",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE directory_context = %s "
            "AND heat >= %s ORDER BY heat DESC",
            (directory, min_heat),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_hot_memories(
        self, min_heat: float = 0.7, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE heat >= %s ORDER BY heat DESC LIMIT %s",
            (min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, heat, embedding FROM memories WHERE embedding IS NOT NULL"
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("embedding") is not None:
                from mcp_server.infrastructure.pg_store import PgMemoryStore

                d["embedding"] = PgMemoryStore._vector_to_bytes(d["embedding"])
            results.append(d)
        return results

    def get_all_memories_for_validation(
        self, limit: int = 1000
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE NOT is_stale "
            "ORDER BY last_accessed ASC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_created_after(
        self, iso_timestamp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE created_at >= %s "
            "ORDER BY created_at ASC LIMIT %s",
            (iso_timestamp, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_in_time_window(
        self, center_time: str, window_minutes: int
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE "
            "ABS(EXTRACT(EPOCH FROM (created_at - %s::timestamptz))) / 60 <= %s",
            (center_time, window_minutes),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_for_decay(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE NOT is_stale"
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def delete_memories_by_tag(self, tag: str) -> int:
        """Delete all memories containing the given tag."""
        cur = self._conn.execute(
            "DELETE FROM memories WHERE tags @> %s::jsonb",
            (json.dumps([tag]),),
        )
        self._conn.commit()
        return cur.rowcount
