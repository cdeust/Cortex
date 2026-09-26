"""Search and retrieval mixin for SqliteMemoryStore.

Implements client-side score fusion (max-normalised weighted sum, the
semantics of the PL/pgSQL ``recall_memories``), FTS5 search, vector search,
and spread activation — replacing PL/pgSQL stored procedures.
"""

from __future__ import annotations

import json
import math
import sqlite3
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from typing import Any

import numpy as np

from mcp_server.observability import silent_failure
from mcp_server.shared.code_tokenize import expand_fts_query as _expand_fts_query
from mcp_server.infrastructure.embedding_engine import current_embedding_mode
from mcp_server.infrastructure.sqlite_scope_clause import directory_scope_clause


_SCORE_FLOOR = 0.001  # source: pg_schema.py recall_memories (floor)
_COSINE_SHIFT = -1.0  # source: pg_schema.py recall_memories (vector)
_RECENCY_DECAY_PER_DAY = 0.01  # source: pg_schema.py recall_memories (recency)


def _normalised(
    raw: dict[int, float], weight: float, shift: float = 0.0
) -> dict[int, float]:
    """``weight * (raw - shift) / max(max(raw) - shift, floor)`` per id.

    source: pg_schema.py recall_memories, ``fused`` CTE"""
    hi = max(raw.values()) if raw else _SCORE_FLOOR
    denominator = max(hi - shift, _SCORE_FLOOR)
    return {i: weight * (v - shift) / denominator for i, v in raw.items()}


def _fuse(contributions: list[dict[int, float]]) -> dict[int, float]:
    scores: dict[int, float] = {}
    for contribution in contributions:
        for memory_id, value in contribution.items():
            scores[memory_id] = scores.get(memory_id, 0.0) + value
    return scores


def _decode_tags(raw: Any) -> list:
    """Deserialize a SQLite ``tags`` TEXT column into a list.

    source: ADR-0616"""
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return raw or []


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
        """Max-normalised weighted score fusion, as PL/pgSQL ``recall_memories``.

        No trigram signal on SQLite; ``wrrf_k`` only scales the agent bonus.

        source: ADR-0616"""
        w = weights or {}
        w_vector = w.get("vector", 1.0)
        pool = max_results * 10
        scores = self._fused_scores(
            query_text, query_embedding, w, pool, min_heat, domain, directory
        )
        self._apply_agent_boost(scores, agent_topic, w_vector, wrrf_k)
        self._apply_trust_factor(scores, trusted_origins, untrusted_factor)

        if not scores:
            return []
        return self._fetch_ranked_results(
            scores, max_results, min_heat, domain, directory
        )

    def _fused_scores(
        self,
        query_text: str,
        query_embedding: bytes | None,
        w: dict[str, float],
        pool: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> dict[int, float]:
        w_vector = w.get("vector", 1.0)
        w_fts = w.get("fts", 0.5)
        w_heat = w.get("heat", 0.3)
        w_recency = w.get("recency", 0.0)
        vector = self._signal_vector(query_embedding, w_vector, pool)
        fts = self._signal_fts(query_text, w_fts, pool)
        heat = self._signal_heat(w_heat, pool, min_heat, domain, directory)
        recency = self._signal_recency(w_recency, pool, min_heat, domain, directory)
        return _fuse(
            [
                _normalised(vector, w_vector, _COSINE_SHIFT),
                _normalised(fts, w_fts),
                _normalised(heat, w_heat),
                _normalised(recency, w_recency),
            ]
        )

    def _signal_vector(
        self,
        query_embedding: bytes | None,
        weight: float,
        pool: int,
    ) -> dict[int, float]:
        """Cosine similarity per KNN hit.

        sqlite-vec returns the L2 distance ``d``; for the unit vectors the
        embedding engine produces, ``cos = 1 - d**2 / 2``.
        """
        if not self._has_vec or query_embedding is None or weight <= 0:
            return {}
        vec = self._bytes_to_vector(query_embedding)
        if vec is None:
            return {}
        try:
            rows = self._conn.execute(
                "SELECT rowid, distance FROM memories_vec "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (vec.tobytes(), pool),
            ).fetchall()
            # source: ADR-0616
            keep = self._vec_rows_in_query_space([r["rowid"] for r in rows])
            return {
                r["rowid"]: 1.0 - r["distance"] ** 2 / 2.0
                for r in rows
                if r["rowid"] in keep
            }
        except Exception as exc:  # noqa: BLE001 — search degrades to the remaining signals
            silent_failure.note("sqlite_store.fusion_vector_signal", exc)
            return {}

    def _signal_fts(
        self,
        query_text: str,
        weight: float,
        pool: int,
    ) -> dict[int, float]:
        """BM25 relevance per FTS5 hit (``-rank``: FTS5 ranks are negative)."""
        if not query_text or weight <= 0:
            return {}
        match = _expand_fts_query(query_text)
        if not match:
            return {}
        try:
            rows = self._conn.execute(
                "SELECT rowid, rank FROM memories_fts "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, pool),
            ).fetchall()
            return {r["rowid"]: -r["rank"] for r in rows}
        except Exception as exc:  # noqa: BLE001 — search degrades to the remaining signals
            silent_failure.note("sqlite_store.fusion_fts_signal", exc)
            return {}

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
        weight: float,
        pool: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> dict[int, float]:
        if weight <= 0:
            return {}
        conds, params = self._build_filter(min_heat, domain, directory)
        params.append(pool)
        rows = self._conn.execute(
            f"SELECT id, heat_base FROM current_memories WHERE {' AND '.join(conds)} "  # noqa: S608 — conditions are in-code literal fragments from _build_filter; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"ORDER BY heat_base DESC LIMIT ?",
            params,
        ).fetchall()
        return {r["id"]: r["heat_base"] for r in rows}

    def _signal_recency(
        self,
        weight: float,
        pool: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> dict[int, float]:
        """``exp(-0.01 * age_days)`` for the ``pool`` most recent memories."""
        if weight <= 0:
            return {}
        conds, params = self._build_filter(min_heat, domain, directory)
        params.append(pool)
        rows = self._conn.execute(
            "SELECT id, julianday('now') - julianday(created_at) AS age_days "  # noqa: S608 — conditions are in-code literal fragments from _build_filter; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            f"FROM current_memories WHERE {' AND '.join(conds)} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return {
            r["id"]: math.exp(-_RECENCY_DECAY_PER_DAY * (r["age_days"] or 0.0))
            for r in rows
        }

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

    def _fetch_ranked_results(
        self,
        scores: dict[int, float],
        max_results: int,
        min_heat: float,
        domain: str | None,
        directory: str | None,
    ) -> list[dict[str, Any]]:
        top_ids = sorted(scores, key=scores.get, reverse=True)[: max_results * 3]  # type: ignore[arg-type]
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
                "ORDER BY memories_fts.rank LIMIT ?",
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

    def spread_activation_memories(
        self,
        query_terms: list[str],
        decay: float = 0.65,
        threshold: float = 0.1,
        max_depth: int = 3,
        max_results: int = 50,
        min_heat: float = 0.05,
        domain: str | None = None,
        include_globals: bool = True,
    ) -> list[tuple[int, float]]:
        """Client-side spread activation: query terms -> entities -> memories.

        source: ADR-0616"""
        seed_entities = self._resolve_seed_entities(query_terms, min_heat)
        if not seed_entities:
            return []
        activated = self._propagate_activation(
            seed_entities, decay, threshold, max_depth
        )
        return self._map_entities_to_memories(
            activated, min_heat, max_results, domain, include_globals
        )

    def _resolve_seed_entities(
        self, query_terms: list[str], min_heat: float
    ) -> dict[int, float]:
        seeds: dict[int, float] = {}
        for term in query_terms:
            rows = self._conn.execute(
                "SELECT id FROM entities "
                "WHERE LOWER(name) = LOWER(?) AND heat >= ? AND NOT archived",
                (term, min_heat),
            ).fetchall()
            for r in rows:
                seeds[r["id"]] = 1.0
        return seeds

    def _propagate_activation(
        self,
        seeds: dict[int, float],
        decay: float,
        threshold: float,
        max_depth: int,
    ) -> dict[int, float]:
        activated = dict(seeds)
        frontier = dict(seeds)
        for _ in range(max_depth):
            next_frontier: dict[int, float] = {}
            for eid, act in frontier.items():
                rels = self._conn.execute(
                    "SELECT source_entity_id, target_entity_id, weight, confidence "
                    "FROM relationships "
                    "WHERE source_entity_id = ? OR target_entity_id = ?",
                    (eid, eid),
                ).fetchall()
                for r in rels:
                    neighbor = (
                        r["target_entity_id"]
                        if r["source_entity_id"] == eid
                        else r["source_entity_id"]
                    )
                    new_act = act * decay * r["weight"] * r["confidence"]
                    if new_act >= threshold:
                        if neighbor not in activated or new_act > activated[neighbor]:
                            activated[neighbor] = new_act
                            next_frontier[neighbor] = new_act
            frontier = next_frontier
            if not frontier:
                break
        return activated

    def _map_entities_to_memories(
        self,
        activated: dict[int, float],
        min_heat: float,
        max_results: int,
        domain: str | None = None,
        include_globals: bool = True,
    ) -> list[tuple[int, float]]:
        """Precondition: none. Postcondition: every returned memory_id either
                belongs to ``domain`` or, when ``include_globals`` is True, carries
                ``is_global = 1`` -- unless ``domain`` is None, in which case no
                filter is applied (mirrors the PL/pgSQL p_domain IS NULL branch).

        source: ADR-0616"""
        memory_acts: dict[int, float] = {}
        for eid, act in activated.items():
            entity = self._conn.execute(
                "SELECT name FROM entities WHERE id = ? AND heat >= ? AND NOT archived",
                (eid, min_heat),
            ).fetchone()
            if not entity:
                continue
            name = entity["name"]
            mem_rows = self._conn.execute(
                "SELECT id, domain, is_global FROM current_memories "
                "WHERE content LIKE ? AND heat_base >= ? AND NOT is_stale LIMIT 20",
                (f"%{name}%", min_heat),
            ).fetchall()
            for mr in mem_rows:
                if domain is not None:
                    same_domain = mr["domain"] == domain
                    is_global_row = include_globals and bool(mr["is_global"])
                    if not (same_domain or is_global_row):
                        continue
                mid = mr["id"]
                if mid not in memory_acts or act > memory_acts[mid]:
                    memory_acts[mid] = act
        sorted_results = sorted(memory_acts.items(), key=lambda x: x[1], reverse=True)
        return sorted_results[:max_results]

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
