"""Session-based memory retrieval mixin for PgMemoryStore.

Provides temporal browsing: list sessions, fetch memories by session,
and backfill session_id for existing memories via temporal clustering.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg


class PgSessionMixin:
    """Session-based memory queries on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    # ── Session listing ──────────────────────────────────────────────

    def get_sessions(
        self,
        domain: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return sessions with memory counts, date range, and domains.

        Groups memories by session_id, ordered by most recent first.
        """
        domain_clause = ""
        params: list[Any] = []

        if domain:
            domain_clause = "AND domain = %s"
            params.append(domain)

        params.append(limit)

        rows = self._conn.execute(
            f"""
            SELECT
                session_id,
                COUNT(*) AS memory_count,
                MIN(created_at) AS first_at,
                MAX(created_at) AS last_at,
                ARRAY_AGG(DISTINCT domain) FILTER (WHERE domain != '') AS domains
            FROM memories
            WHERE session_id != ''
                AND NOT is_benchmark
                {domain_clause}
            GROUP BY session_id
            ORDER BY MAX(created_at) DESC
            LIMIT %s
            """,
            params,
        ).fetchall()

        results = []
        for r in rows:
            row = dict(r)
            # Normalize datetime fields to ISO strings
            for field in ("first_at", "last_at"):
                if isinstance(row.get(field), datetime):
                    row[field] = row[field].isoformat()
            # Normalize domains array
            row["domains"] = row.get("domains") or []
            results.append(row)
        return results

    # ── Memories by session ──────────────────────────────────────────

    def get_memories_by_session(
        self,
        session_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return memories in a session ordered by created_at."""
        rows = self._conn.execute(
            """
            SELECT id, content, tags, source, domain, created_at,
                   heat, importance, store_type, consolidation_stage,
                   session_id, is_protected, emotional_valence
            FROM memories
            WHERE session_id = %s
                AND NOT is_benchmark
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (session_id, limit),
        ).fetchall()

        return [self._normalize_memory_row(r) for r in rows]

    # ── Backfill session IDs ─────────────────────────────────────────

    def infer_session_ids(self, window_hours: float = 2.0) -> int:
        """Backfill session_id for memories without one.

        Groups memories by temporal proximity (within window_hours),
        assigns session_id = ISO date-hour string (e.g. '2026-04-03T14').

        Returns count of memories updated.
        """
        # Fetch unassigned memories ordered by time
        rows = self._conn.execute(
            """
            SELECT id, created_at
            FROM memories
            WHERE (session_id IS NULL OR session_id = '')
                AND NOT is_benchmark
            ORDER BY created_at ASC
            """
        ).fetchall()

        if not rows:
            return 0

        # Group by temporal proximity
        groups: list[list[dict]] = []
        current_group: list[dict] = [dict(rows[0])]

        for row in rows[1:]:
            prev = current_group[-1]["created_at"]
            curr = row["created_at"]
            if isinstance(prev, datetime) and isinstance(curr, datetime):
                diff_hours = (curr - prev).total_seconds() / 3600.0
                if diff_hours <= window_hours:
                    current_group.append(dict(row))
                    continue
            groups.append(current_group)
            current_group = [dict(row)]
        groups.append(current_group)

        # Assign session IDs
        updated = 0
        for group in groups:
            first_ts = group[0]["created_at"]
            if isinstance(first_ts, datetime):
                session_id = first_ts.strftime("%Y-%m-%dT%H")
            else:
                session_id = str(first_ts)[:13]

            ids = [g["id"] for g in group]
            self._conn.execute(
                "UPDATE memories SET session_id = %s WHERE id = ANY(%s)",
                (session_id, ids),
            )
            updated += len(ids)

        self._conn.commit()
        return updated
