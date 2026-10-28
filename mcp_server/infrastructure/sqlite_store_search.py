"""Search mixin for SqliteMemoryStore: FTS5 and sqlite-vec listings, and the
FTS5 recall signal.

The recall fusion lives in ``sqlite_store_recall.py`` and the vector, heat and
recency signals in ``sqlite_store_recall_signals.py`` (ADR-1109 split).

source: ADR-0616
"""

from __future__ import annotations

import sqlite3
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from typing import Any

import numpy as np

from mcp_server.observability import silent_failure
from mcp_server.shared.code_tokenize import expand_fts_query as _expand_fts_query
from mcp_server.infrastructure.sqlite_scope_clause import directory_scope_clause
from mcp_server.shared.tie_groups import TieGroup, group_credit, ranked_credits

# source: ADR-1109 -- fusion position of the FTS5 signal (vector 0, FTS5 1,
# heat 2, recency 3; sqlite_store_recall_signals.py).
FTS = 1


class SqliteSearchMixin:
    """FTS5 and sqlite-vec search operations on SQLite."""

    _conn: PsycopgCompatConnection
    _has_vec: bool

    @staticmethod
    def _bytes_to_vector(emb: bytes | None) -> np.ndarray | None:
        """Provided by SqliteMemoryStore."""
        ...

    def _signal_fts(
        self, query_text: str, weight: float, k: int, pool: int
    ) -> tuple[list[tuple[int, float]], TieGroup | None]:
        """Rank-fuse the FTS5 pool by ``bm25``; a boundary group past the
        pool comes back as a ``TieGroup`` (ADR-1109).

        source: ADR-1109"""
        if not query_text or weight <= 0:
            return [], None
        match = _expand_fts_query(query_text)
        if not match:
            return [], None
        try:
            return self._fts_pool(match, weight, k, pool)
        except Exception as exc:  # noqa: BLE001 — record and propagate; partial fusion is not a search result
            silent_failure.note("sqlite_store.rrf_fts_signal", exc)
            raise

    def _fts_pool(
        self, match: str, weight: float, k: int, pool: int
    ) -> tuple[list[tuple[int, float]], TieGroup | None]:
        """source: ADR-1109"""
        rows = self._conn.execute(
            "SELECT rowid, bm25(memories_fts) AS score FROM memories_fts "
            "WHERE memories_fts MATCH ? ORDER BY score LIMIT ?",
            (match, pool + 1),
        ).fetchall()
        if len(rows) <= pool or rows[pool]["score"] != rows[pool - 1]["score"]:
            ranked = [(r["rowid"], r["score"]) for r in rows[:pool]]
            return ranked_credits(ranked, weight, k), None
        boundary = rows[pool - 1]["score"]
        head = [(r["rowid"], r["score"]) for r in rows[:pool] if r["score"] != boundary]
        tied = "FROM memories_fts WHERE memories_fts MATCH ? AND bm25(memories_fts) = ?"
        size = self._conn.execute(
            f"SELECT count(*) AS n {tied}",
            (match, boundary),  # noqa: S608 — tied is an in-code literal; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        ).fetchall()[0]["n"]
        credit = group_credit(len(head), size, weight, k)
        where = f"m.id IN (SELECT rowid {tied})"
        return ranked_credits(head, weight, k), TieGroup(
            FTS, credit, where, (match, boundary)
        )

    def search_fts(
        self,
        query: str,
        limit: int = 20,
        directory_ancestors: list[str] | None = None,
    ) -> list[tuple[int, float]]:
        """Full-text search via FTS5. Returns (memory_id, score) pairs.

        directory_ancestors, when not None, restricts rows to is_global or
        an ancestor directory_context, applied before ORDER BY/LIMIT so
        the limit is never spent on rows the caller cannot use (issue
        #604 follow-up).

        source: ADR-0616"""
        # source: ADR-0616
        scope_filter, scope_params = directory_scope_clause(
            directory_ancestors, column_prefix="m."
        )
        try:
            rows = self._conn.execute(
                "SELECT memories_fts.rowid AS rowid, memories_fts.rank AS rank "  # noqa: S608 — scope_filter is a fixed in-code fragment from directory_scope_clause; values are bound parameters (docs/ASSURANCE-CASE.md §5)
                "FROM memories_fts "
                "JOIN current_memories m ON m.id = memories_fts.rowid "
                "WHERE memories_fts MATCH ? AND NOT m.is_stale "
                f"{scope_filter}"
                # source: ADR-1106 -- exact ties go to the newer memory.
                "ORDER BY memories_fts.rank, m.created_at DESC, m.id DESC LIMIT ?",
                (query, *scope_params, limit),
            ).fetchall()
            return [(r["rowid"], -r["rank"]) for r in rows]
        except sqlite3.Error:
            return []

    def search_vectors(
        self,
        query_embedding: bytes,
        top_k: int = 10,
        min_heat: float = 0.0,
        heads_only: bool = False,
    ) -> list[tuple[int, float]]:
        """Vector KNN search via sqlite-vec. Returns (memory_id, distance).

        source: ADR-0616"""
        if not self._has_vec:
            return []
        vec = self._bytes_to_vector(query_embedding)
        if vec is None:
            return []
        rows = self._conn.execute(
            "SELECT rowid, distance FROM memories_vec "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (vec.tobytes(), top_k),
        ).fetchall()
        results = [(r["rowid"], r["distance"]) for r in rows]
        if heads_only and results:
            ids = [rid for rid, _ in results]
            placeholders = ",".join("?" * len(ids))
            current = {
                r["id"]
                for r in self._conn.execute(
                    f"SELECT id FROM current_memories WHERE id IN ({placeholders})",  # noqa: S608 — interpolation is a generated ?/%s placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
                    ids,
                ).fetchall()
            }
            results = [(rid, d) for rid, d in results if rid in current]
        return results

    def get_hot_embeddings(
        self,
        min_heat: float = 0.05,
        domain: str | None = None,
        limit: int = 500,
    ) -> list[tuple[int, Any, float]]:
        """Fetch hot memory IDs, then load their sqlite-vec embeddings by rowid.

        source: ADR-0616"""
        # precondition: heat column is heat_base in SQLite schema (A3 migration)
        conds = ["heat_base >= ?", "NOT is_stale"]
        params: list[Any] = [min_heat]
        if domain:
            conds.append("(domain = ? OR is_global = 1)")
            params.append(domain)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT id, heat_base FROM memories WHERE {' AND '.join(conds)} "  # noqa: S608 — conditions are in-code literal fragments from _build_filter; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"ORDER BY heat_base DESC LIMIT ?",
            params,
        ).fetchall()
        if not rows:
            return []
        results: list[tuple[int, Any, float]] = []
        for row in rows:
            mid = row["id"] if hasattr(row, "__getitem__") else row[0]
            heat_val = row["heat_base"] if hasattr(row, "__getitem__") else row[1]
            emb = self._fetch_embedding_bytes(mid)
            if emb is not None:
                results.append((mid, emb, float(heat_val)))
        return results

    def _fetch_embedding_bytes(self, memory_id: int) -> bytes | None:
        """Fetch raw embedding bytes from memories_vec for a single memory.

        Precondition: memory_id is a valid integer.
        Postcondition: returns bytes (numpy float32 packed) or None if the
          vec table is absent, the row is missing, or the embedding is NULL.
        """
        if not self._has_vec:
            return None
        try:
            vec_row = self._conn.execute(
                "SELECT embedding FROM memories_vec WHERE rowid = ?",
                (memory_id,),
            ).fetchone()
            if vec_row is None:
                return None
            raw = vec_row["embedding"]
            if raw is None:
                return None
            # sqlite-vec returns a buffer/memoryview; convert to bytes.
            return bytes(raw)
        except sqlite3.Error:
            return None

    def get_temporal_co_access(
        self,
        window_hours: float = 2.0,
        min_access: int = 1,
        limit: int = 100,
    ) -> list[tuple[int, int, float]]:
        """Return (mem_a, mem_b, proximity_weight) pairs co-accessed recently.

                Precondition: window_hours > 0; limit >= 1.
                Postcondition: a < b (canonical pair order); w in (0,1]; ordered DESC;
                  len <= limit.

        source: ADR-0616"""
        window_seconds = window_hours * 3600.0
        try:
            rows = self._conn.execute(
                """
                SELECT
                    CASE WHEN a.id < b.id THEN a.id ELSE b.id END AS mem_a,
                    CASE WHEN a.id < b.id THEN b.id ELSE a.id END AS mem_b,
                    1.0 - (
                        ABS(
                            (julianday(a.last_accessed) - julianday(b.last_accessed))
                            * 86400.0
                        ) / ?
                    ) AS proximity
                FROM memories a
                JOIN memories b
                    ON a.id != b.id
                    AND ABS(
                        (julianday(a.last_accessed) - julianday(b.last_accessed))
                        * 86400.0
                    ) < ?
                WHERE a.access_count >= ?
                  AND NOT a.is_stale
                  AND b.access_count >= ?
                  AND NOT b.is_stale
                GROUP BY mem_a, mem_b
                ORDER BY proximity DESC
                LIMIT ?
                """,
                (
                    window_seconds,
                    window_seconds,
                    min_access,
                    min_access,
                    limit,
                ),
            ).fetchall()
        except sqlite3.Error:
            return []
        results: list[tuple[int, int, float]] = []
        for row in rows:
            if hasattr(row, "__getitem__"):
                mem_a, mem_b, proximity = row["mem_a"], row["mem_b"], row["proximity"]
            else:
                mem_a, mem_b, proximity = row[0], row[1], row[2]
            if proximity is None or proximity <= 0:
                continue
            results.append((int(mem_a), int(mem_b), float(min(1.0, proximity))))
        return results
