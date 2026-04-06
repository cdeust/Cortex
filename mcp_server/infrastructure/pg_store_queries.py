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
        rows = self._execute(
            "SELECT * FROM memories WHERE (domain = %s OR is_global = TRUE) "
            "AND heat >= %s ORDER BY heat DESC LIMIT %s",
            (domain, min_heat, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_for_directory(
        self, directory: str, min_heat: float = 0.05
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE (directory_context = %s OR is_global = TRUE) "
            "AND heat >= %s ORDER BY heat DESC",
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
            rows = self._execute(
                "SELECT * FROM memories WHERE heat >= %s ORDER BY heat DESC LIMIT %s",
                (min_heat, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM memories WHERE heat >= %s "
                "AND NOT coalesce(is_benchmark, FALSE) "
                "ORDER BY heat DESC LIMIT %s",
                (min_heat, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_with_embeddings(self) -> list[dict[str, Any]]:
        rows = self._execute(
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
        rows = self._execute(
            "SELECT * FROM memories WHERE NOT is_stale "
            "ORDER BY last_accessed ASC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_created_after(
        self, iso_timestamp: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE created_at >= %s "
            "ORDER BY created_at ASC LIMIT %s",
            (iso_timestamp, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_memories_in_time_window(
        self, center_time: str, window_minutes: int
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE "
            "ABS(EXTRACT(EPOCH FROM (created_at - %s::timestamptz))) / 60 <= %s",
            (center_time, window_minutes),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_all_memories_for_decay(self) -> list[dict[str, Any]]:
        rows = self._execute("SELECT * FROM memories WHERE NOT is_stale").fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def search_by_tag_vector(
        self,
        query_embedding: bytes | None,
        tag: str,
        domain: str | None = None,
        min_heat: float = 0.01,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Vector search filtered by tag. Returns scored memories.

        ENGRAM (arxiv 2511.12960): per-type retrieval pools guarantee
        typed memories (preference, instruction) are not drowned out.
        """
        import numpy as np

        emb = (
            np.frombuffer(query_embedding, dtype=np.float32)
            if query_embedding
            else None
        )
        if emb is not None:
            rows = self._execute(
                "SELECT *, (1.0 - (embedding <=> %s))::REAL AS score "
                "FROM memories "
                "WHERE tags @> %s::jsonb AND heat >= %s AND NOT is_stale "
                "AND embedding IS NOT NULL "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY embedding <=> %s LIMIT %s",
                (emb, json.dumps([tag]), min_heat, domain, domain, emb, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT *, heat::REAL AS score "
                "FROM memories "
                "WHERE tags @> %s::jsonb AND heat >= %s AND NOT is_stale "
                "AND ((%s::TEXT IS NULL) OR domain = %s OR is_global = TRUE) "
                "ORDER BY heat DESC LIMIT %s",
                (json.dumps([tag]), min_heat, domain, domain, limit),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def delete_memories_by_tag(self, tag: str) -> int:
        """Delete all memories containing the given tag."""
        cur = self._execute(
            "DELETE FROM memories WHERE tags @> %s::jsonb",
            (json.dumps([tag]),),
        )
        self._conn.commit()
        return cur.rowcount
