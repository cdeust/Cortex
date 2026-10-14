"""Search and retrieval mixin for SqliteMemoryStore.

Implements client-side WRRF fusion, FTS5 search, vector search,
and spread activation — replacing PL/pgSQL stored procedures.
"""

from __future__ import annotations

import json
import sqlite3
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from typing import Any

import numpy as np

from mcp_server.observability import silent_failure
from mcp_server.shared.code_tokenize import expand_fts_query as _expand_fts_query
from mcp_server.infrastructure.embedding_engine import current_embedding_mode
from mcp_server.infrastructure.sqlite_scope_clause import directory_scope_clause
from mcp_server.shared.tie_groups import fetch_with_ties, tied_rrf


def _decode_tags(raw: Any) -> list:
    """Deserialize a SQLite ``tags`` TEXT column into a list.

    source: ADR-0616"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return raw or []


def _add(scores: dict[int, float], credit: dict[int, float]) -> None:
    """Add one signal's credit into the fused scores.

    source: ADR-0616"""
    for mid, c in credit.items():
        scores[mid] = scores.get(mid, 0) + c


class SqliteSearchMixin:
    """Search operations on SQLite with client-side WRRF fusion."""

    _conn: PsycopgCompatConnection
    _has_vec: bool

    @staticmethod
    def _bytes_to_vector(emb: bytes | None) -> np.ndarray | None:
        """Provided by SqliteMemoryStore."""
        ...

    def recall_memories(
        self,
        query_text: str,
        query_embedding: bytes | None,
        intent: str = "general",
        domain: str | None = None,
        directory: str | None = None,
        agent_topic: str | None = None,
        min_heat: float = 0.05,
        max_results: int = 10,
        wrrf_k: int = 60,
        weights: dict[str, float] | None = None,
        include_globals: bool = True,
        trusted_origins: tuple[str, ...] = (),
        untrusted_factor: float = 1.0,
    ) -> list[dict[str, Any]]:
        """Client-side WRRF fusion: vector + FTS5 + heat + recency.

        source: ADR-0616"""
        w = weights or {}
        w_vector = w.get("vector", 1.0)
        w_fts = w.get("fts", 0.5)
        w_heat = w.get("heat", 0.3)
        w_recency = w.get("recency", 0.0)
        pool = max_results * 10
        scores: dict[int, float] = {}

        self._signal_vector(scores, query_embedding, w_vector, wrrf_k, pool)
        self._signal_fts(scores, query_text, w_fts, wrrf_k, pool)
        self._signal_heat(scores, w_heat, wrrf_k, pool, min_heat, domain, directory)
        self._signal_recency(
            scores, w_recency, wrrf_k, pool, min_heat, domain, directory
        )
        self._apply_agent_boost(scores, agent_topic, w_vector, wrrf_k)
        self._apply_trust_factor(scores, trusted_origins, untrusted_factor)

        if not scores:
            return []
        return self._fetch_ranked_results(
            scores, max_results, min_heat, domain, directory
        )

    def _signal_vector(
        self,
        scores: dict[int, float],
        query_embedding: bytes | None,
        weight: float,
        k: int,
        pool: int,
    ) -> None:
        if not self._has_vec or query_embedding is None or weight <= 0:
            return
        vec = self._bytes_to_vector(query_embedding)
        if vec is None:
            return
        try:
            # source: ADR-1109 -- vec0's KNN cut cannot keep ties, so the cut
            # is widened until the boundary distance group is whole.
            rows = fetch_with_ties(
                lambda n: self._conn.execute(
                    "SELECT rowid, distance FROM memories_vec "
                    "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                    (vec.tobytes(), n),
                ).fetchall(),
                pool,
                lambda r: r["distance"],
            )
            # source: ADR-0616
            keep = self._vec_rows_in_query_space([r["rowid"] for r in rows])
            ranked = [(r["rowid"], r["distance"]) for r in rows if r["rowid"] in keep]
            _add(scores, tied_rrf(ranked, weight, k))
        except Exception as exc:  # noqa: BLE001 — search degrades to the remaining signals
            silent_failure.note("sqlite_store.rrf_vector_signal", exc)

    def _signal_fts(
        self,
        scores: dict[int, float],
        query_text: str,
        weight: float,
        k: int,
        pool: int,
    ) -> None:
        if not query_text or weight <= 0:
            return
        match = _expand_fts_query(query_text)
        if not match:
            return
        try:
            # source: ADR-1109 -- the boundary rank group is kept whole and
            # tied rows share their positions' credit.
            rows = fetch_with_ties(
                lambda n: self._conn.execute(
                    "SELECT rowid, rank FROM memories_fts "
                    "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                    (match, n),
                ).fetchall(),
                pool,
                lambda r: r["rank"],
            )
            ranked = [(r["rowid"], r["rank"]) for r in rows]
            _add(scores, tied_rrf(ranked, weight, k))
        except Exception as exc:  # noqa: BLE001 — search degrades to the remaining signals
            silent_failure.note("sqlite_store.rrf_fts_signal", exc)

    def _vec_rows_in_query_space(self, rowids: list[int]) -> set[int]:
        """Subset of ``rowids`` whose embedding space matches the query's.

        precondition: ``rowids`` are memory ids returned by the vec KNN.
                postcondition: returns the ids whose ``memories.embedding_model`` is
                compatible with the current process embedding mode :
                a neural query keeps 'neural' and legacy '' rows; a fallback query keeps
                only 'fallback' rows; an 'unknown' mode (no engine constructed — e.g. a
                raw-vector unit test) keeps everything. Fail-open on a missing column.

        source: ADR-0616"""
        if not rowids:
            return set()

        mode = current_embedding_mode()
        if mode == "unknown":
            return set(rowids)
        compatible = {"neural", ""} if mode == "neural" else {"fallback"}
        placeholders = ",".join("?" * len(rowids))
        try:
            rows = self._conn.execute(
                f"SELECT id, embedding_model FROM memories "  # noqa: S608 — interpolation is a generated ?/%s placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
                f"WHERE id IN ({placeholders})",
                rowids,
            ).fetchall()
        except sqlite3.OperationalError:
            return set(rowids)
        return {r["id"] for r in rows if (r["embedding_model"] or "") in compatible}

    def _signal_heat(
        self,
        scores: dict[int, float],
        weight: float,
        k: int,
        pool: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> None:
        if weight <= 0:
            return
        # source: ADR-1106 -- (heat_base DESC, id DESC) keeps the index plan.
        self._signal_column(
            scores,
            "heat_base",
            "heat_base DESC, id DESC",
            weight,
            k,
            pool,
            self._build_filter(min_heat, domain, directory),
        )

    def _signal_recency(
        self,
        scores: dict[int, float],
        weight: float,
        k: int,
        pool: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> None:
        if weight <= 0:
            return
        self._signal_column(
            scores,
            "created_at",
            "created_at DESC, id DESC",
            weight,
            k,
            pool,
            self._build_filter(min_heat, domain, directory),
        )

    def _signal_column(
        self,
        scores: dict[int, float],
        column: str,
        order: str,
        weight: float,
        k: int,
        pool: int,
        where: tuple[list[str], list[Any]],
    ) -> None:
        """Rank-fuse one stored column; its boundary tie group is kept whole
        and tied rows share their positions' credit.

        source: ADR-1109"""
        conds, params = where
        sql = (
            f"SELECT id, {column} AS score FROM current_memories "  # noqa: S608 — column, order and conditions are in-code literals; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"WHERE {' AND '.join(conds)} ORDER BY {order} LIMIT ?"
        )
        rows = fetch_with_ties(
            lambda n: self._conn.execute(sql, [*params, n]).fetchall(),
            pool,
            lambda r: r["score"],
        )
        _add(scores, tied_rrf([(r["id"], r["score"]) for r in rows], weight, k))

    @staticmethod
    def _build_filter(
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> tuple[list[str], list[Any]]:
        conds = ["heat_base >= ?", "NOT is_stale"]
        params: list[Any] = [min_heat]
        if domain:
            conds.append("(domain = ? OR is_global = 1)")
            params.append(domain)
        if directory:
            conds.append("(directory_context = ? OR is_global = 1)")
            params.append(directory)
        return conds, params

    def _apply_agent_boost(
        self,
        scores: dict[int, float],
        agent_topic: str | None,
        w_vector: float,
        wrrf_k: int,
    ) -> None:
        if not agent_topic or not scores:
            return
        boost = 0.3 * (w_vector / wrrf_k)
        ids = list(scores.keys())
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT id FROM memories WHERE id IN ({placeholders}) "  # noqa: S608 — interpolation is a generated ?/%s placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
            f"AND agent_context = ?",
            [*ids, agent_topic],
        ).fetchall()
        for r in rows:
            scores[r["id"]] += boost

    def _apply_trust_factor(
        self,
        scores: dict[int, float],
        trusted_origins: tuple[str, ...],
        untrusted_factor: float,
    ) -> None:
        """Multiplicative, not additive: an additive penalty cannot demote a
                passage that wins on similarity.

        source: ADR-0616"""
        if not scores or untrusted_factor == 1.0:
            return
        ids = list(scores.keys())
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT id, capture_origin FROM memories WHERE id IN ({placeholders})",  # noqa: S608 — interpolation is a generated ? placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
            ids,
        ).fetchall()
        trusted = set(trusted_origins)
        for r in rows:
            # source: ADR-0616
            if r["capture_origin"] not in trusted:
                scores[r["id"]] *= untrusted_factor

    def _ranked_ids(self, scores: dict[int, float]) -> list[int]:
        """Score order; exact ties go to the newer memory.

        source: ADR-1106"""
        ids = list(scores)
        placeholders = ",".join("?" * len(ids))
        created = {
            r["id"]: r["created_at"]
            for r in self._conn.execute(
                f"SELECT id, created_at FROM memories WHERE id IN ({placeholders})",  # noqa: S608 — interpolation is a generated ? placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
                ids,
            ).fetchall()
        }
        return sorted(ids, key=lambda i: (scores[i], created[i], i), reverse=True)

    def _fetch_ranked_results(
        self,
        scores: dict[int, float],
        max_results: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> list[dict[str, Any]]:
        top_ids = self._ranked_ids(scores)[: max_results * 3]
        placeholders = ",".join("?" * len(top_ids))
        # source: ADR-0616
        rows = self._conn.execute(
            f"SELECT * FROM current_memories WHERE id IN ({placeholders})",  # noqa: S608 — interpolation is a generated ?/%s placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
            top_ids,
        ).fetchall()
        row_map = {r["id"]: r for r in rows}

        results = []
        for mid in top_ids:
            row = row_map.get(mid)
            if row is None:
                continue
            if row["heat_base"] < min_heat or row["is_stale"]:
                continue
            is_global = bool(row.get("is_global", 0))
            if domain and row["domain"] != domain and not is_global:
                continue
            if directory and row["directory_context"] != directory and not is_global:
                continue
            results.append(
                {
                    "memory_id": mid,
                    "content": row["content"],
                    "score": scores[mid],
                    "heat": row["heat_base"],
                    "domain": row["domain"],
                    "created_at": row["created_at"],
                    "store_type": row["store_type"],
                    "tags": _decode_tags(row["tags"]),
                    "importance": row["importance"],
                    "surprise_score": row["surprise_score"],
                    # source: ADR-0616
                    "capture_origin": row["capture_origin"],
                }
            )
        return results

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
        try:
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
        except (sqlite3.Error, ValueError):
            return []

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
