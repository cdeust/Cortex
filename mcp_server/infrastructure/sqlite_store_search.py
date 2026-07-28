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


def _decode_tags(raw: Any) -> list:
    """Deserialize a SQLite ``tags`` TEXT column into a list.

    SQLite stores tags as a JSON string; the ``recall`` output schema (and
    parity with the PostgreSQL backend) requires a list. Mirrors the decode in
    ``SqliteMemoryStore._normalize_memory_row``.
    """
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
    ) -> list[dict[str, Any]]:
        """Client-side WRRF fusion: vector + FTS5 + heat + recency."""
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
            rows = self._conn.execute(
                "SELECT rowid, distance FROM memories_vec "
                "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (vec.tobytes(), pool),
            ).fetchall()
            # Keep only vectors that live in the SAME space as the query
            # embedding (issue #169): a 'fallback' (algorithmic) vector and a
            # 'neural' vector are geometrically incompatible, so their cosine
            # distances are not comparable. Cross-space rows still surface via
            # FTS/heat/recency — they are only barred from the vector signal.
            keep = self._vec_rows_in_query_space([r["rowid"] for r in rows])
            rank = 0
            for r in rows:
                if r["rowid"] not in keep:
                    continue
                rank += 1
                scores[r["rowid"]] = scores.get(r["rowid"], 0) + weight / (k + rank)
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
            rows = self._conn.execute(
                "SELECT rowid, rank FROM memories_fts "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, pool),
            ).fetchall()
            for rank, r in enumerate(rows, 1):
                scores[r["rowid"]] = scores.get(r["rowid"], 0) + weight / (k + rank)
        except Exception as exc:  # noqa: BLE001 — search degrades to the remaining signals
            silent_failure.note("sqlite_store.rrf_fts_signal", exc)

    def _vec_rows_in_query_space(self, rowids: list[int]) -> set[int]:
        """Subset of ``rowids`` whose embedding space matches the query's.

        precondition: ``rowids`` are memory ids returned by the vec KNN.
        postcondition: returns the ids whose ``memories.embedding_model`` is
        compatible with the current process embedding mode (issue #169):
        a neural query keeps 'neural' and legacy '' rows; a fallback query keeps
        only 'fallback' rows; an 'unknown' mode (no engine constructed — e.g. a
        raw-vector unit test) keeps everything. Fail-open on a missing column.
        """
        if not rowids:
            return set()
        from mcp_server.infrastructure.embedding_engine import current_embedding_mode

        mode = current_embedding_mode()
        if mode == "unknown":
            return set(rowids)
        compatible = {"neural", ""} if mode == "neural" else {"fallback"}
        placeholders = ",".join("?" * len(rowids))
        try:
            rows = self._conn.execute(
                f"SELECT id, embedding_model FROM memories "
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
        conds, params = self._build_filter(min_heat, domain, directory)
        params.append(pool)
        rows = self._conn.execute(
            f"SELECT id FROM current_memories WHERE {' AND '.join(conds)} "
            f"ORDER BY heat_base DESC LIMIT ?",
            params,
        ).fetchall()
        for rank, r in enumerate(rows, 1):
            scores[r["id"]] = scores.get(r["id"], 0) + weight / (k + rank)

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
        conds, params = self._build_filter(min_heat, domain, directory)
        params.append(pool)
        rows = self._conn.execute(
            f"SELECT id FROM current_memories WHERE {' AND '.join(conds)} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        for rank, r in enumerate(rows, 1):
            scores[r["id"]] = scores.get(r["id"], 0) + weight / (k + rank)

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
            f"SELECT id FROM memories WHERE id IN ({placeholders}) "
            f"AND agent_context = ?",
            [*ids, agent_topic],
        ).fetchall()
        for r in rows:
            scores[r["id"]] += boost

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
        # current_memories: the vector/FTS signals read virtual tables
        # (memories_vec/memories_fts) that cannot carry the supersession
        # predicate, so superseded ids can enter `scores`. This ranked-fetch
        # gate is the SQLite analog of the PG candidates-CTE exclusion:
        # superseded rows vanish from row_map and are skipped. They may still
        # consume vector/FTS pool slots — acceptable at fallback scale, same
        # argument as the O(N) embedding join in get_hot_embeddings.
        rows = self._conn.execute(
            f"SELECT * FROM current_memories WHERE id IN ({placeholders})",
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
                }
            )
        return results

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search via FTS5. Returns (memory_id, score) pairs.

        Joined on current_memories + NOT is_stale (mirror of the PG
        search_fts): this is a discovery channel whose hits are injected
        client-side with a fabricated score, so exclusion must happen here —
        no downstream ranking can demote a superseded or stale hit.
        """
        # NOTE: ``query`` here is an already-built FTS5 expression — callers
        # (auto_recall._fts_query_from_prompt, recall_helpers.build_expanded_query)
        # construct their own OR/AND term lists — so it must be passed through
        # verbatim, NOT re-expanded (re-wrapping their operators would turn an OR
        # into a literal AND, issue #169 regression). Code-aware matching on this
        # path is carried entirely by index-time augmentation (augment_content),
        # which indexes both the full identifier and its sub-tokens.
        try:
            rows = self._conn.execute(
                "SELECT memories_fts.rowid AS rowid, memories_fts.rank AS rank "
                "FROM memories_fts "
                "JOIN current_memories m ON m.id = memories_fts.rowid "
                "WHERE memories_fts MATCH ? AND NOT m.is_stale "
                "ORDER BY memories_fts.rank LIMIT ?",
                (query, limit),
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

        heads_only mirrors PgMemoryStore.search_vectors: the vec virtual
        table cannot carry the supersession predicate, so hits are
        post-filtered against current_memories (superseded ids may consume
        top_k slots — acceptable at fallback scale).
        """
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
                        f"SELECT id FROM current_memories WHERE id IN ({placeholders})",
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

        domain/include_globals mirror PgMemoryStore.spread_activation_memories
        (ADR-0054, same substitutability contract): the entity graph stays
        unscoped, but the final entity->memory mapping is filtered to
        ``domain`` (plus is_global rows when include_globals) so the
        SQLite fallback (memory_store.py's inspection-mode path, which
        can serve real traffic) does not reopen the cross-domain
        injection the PostgreSQL fix closes.
        """
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
        """Map activated entities to memory rows, domain-scoped (ADR-0054).

        Precondition: none. Postcondition: every returned memory_id either
        belongs to ``domain`` or, when ``include_globals`` is True, carries
        ``is_global = 1`` -- unless ``domain`` is None, in which case no
        filter is applied (mirrors the PL/pgSQL p_domain IS NULL branch).
        """
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
        """Return (memory_id, embedding_bytes, heat) for hot memories.

        Precondition: min_heat >= 0.0; limit >= 1.
        Postcondition: ordered by heat_base DESC; len <= limit; rows without
          embeddings are excluded; empty list when sqlite-vec is absent.

        Mirrors PgMemoryStore.get_hot_embeddings. SQLite stores embeddings in
        memories_vec (sqlite-vec); we join client-side: fetch hot IDs, then
        fetch each embedding by rowid. Engineering choice: O(N) join is
        acceptable at fallback scale (<10k memories).
        """
        # precondition: heat column is heat_base in SQLite schema (A3 migration)
        conds = ["heat_base >= ?", "NOT is_stale"]
        params: list[Any] = [min_heat]
        if domain:
            conds.append("(domain = ? OR is_global = 1)")
            params.append(domain)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT id, heat_base FROM memories WHERE {' AND '.join(conds)} "
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
            raw = (
                vec_row["embedding"] if hasattr(vec_row, "__getitem__") else vec_row[0]
            )
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

        Mirrors PgMemoryStore.get_temporal_co_access for SR-graph construction.
        SQLite divergence: only one last_accessed timestamp per memory (no
        access log). Approximation: pair memories whose last_accessed differs
        by less than window_hours; proximity = 1 - delta/window (linear decay).
        min_access is honored via access_count >= min_access, mirroring the PG
        stored procedure WHERE clause (pg_schema.py get_temporal_co_access).
        Source: Dayan, P. (1993). "Improving Generalisation for Temporal
        Difference Learning: The Successor Representation." Neural Computation
        5(4), 613-624. Proximity formula adapted from PG stored procedure shape.
        """
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
