"""Search and retrieval mixin for SqliteMemoryStore.

Implements client-side WRRF fusion, FTS5 search, vector search,
and spread activation — replacing PL/pgSQL stored procedures.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import numpy as np


class SqliteSearchMixin:
    """Search operations on SQLite with client-side WRRF fusion."""

    _conn: sqlite3.Connection
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
            for rank, r in enumerate(rows, 1):
                scores[r["rowid"]] = scores.get(r["rowid"], 0) + weight / (k + rank)
        except Exception:
            pass

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
        try:
            rows = self._conn.execute(
                "SELECT rowid, rank FROM memories_fts "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (query_text, pool),
            ).fetchall()
            for rank, r in enumerate(rows, 1):
                scores[r["rowid"]] = scores.get(r["rowid"], 0) + weight / (k + rank)
        except Exception:
            pass

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
            f"SELECT id FROM memories WHERE {' AND '.join(conds)} "
            f"ORDER BY heat DESC LIMIT ?",
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
            f"SELECT id FROM memories WHERE {' AND '.join(conds)} "
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
        conds = ["heat >= ?", "NOT is_stale"]
        params: list[Any] = [min_heat]
        if domain:
            conds.append("domain = ?")
            params.append(domain)
        if directory:
            conds.append("directory_context = ?")
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
        rows = self._conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders})",
            top_ids,
        ).fetchall()
        row_map = {r["id"]: r for r in rows}

        results = []
        for mid in top_ids:
            row = row_map.get(mid)
            if row is None:
                continue
            if row["heat"] < min_heat or row["is_stale"]:
                continue
            if domain and row["domain"] != domain:
                continue
            if directory and row["directory_context"] != directory:
                continue
            results.append(
                {
                    "memory_id": mid,
                    "content": row["content"],
                    "score": scores[mid],
                    "heat": row["heat"],
                    "domain": row["domain"],
                    "created_at": row["created_at"],
                    "store_type": row["store_type"],
                    "tags": row["tags"],
                    "importance": row["importance"],
                    "surprise_score": row["surprise_score"],
                }
            )
        return results

    def search_fts(self, query: str, limit: int = 20) -> list[tuple[int, float]]:
        """Full-text search via FTS5. Returns (memory_id, score) pairs."""
        try:
            rows = self._conn.execute(
                "SELECT rowid, rank FROM memories_fts "
                "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
            return [(r["rowid"], -r["rank"]) for r in rows]
        except Exception:
            return []

    def search_vectors(
        self, query_embedding: bytes, top_k: int = 10, min_heat: float = 0.0
    ) -> list[tuple[int, float]]:
        """Vector KNN search via sqlite-vec. Returns (memory_id, distance)."""
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
            return [(r["rowid"], r["distance"]) for r in rows]
        except Exception:
            return []

    def spread_activation_memories(
        self,
        query_terms: list[str],
        decay: float = 0.65,
        threshold: float = 0.1,
        max_depth: int = 3,
        max_results: int = 50,
        min_heat: float = 0.05,
    ) -> list[tuple[int, float]]:
        """Client-side spread activation: query terms -> entities -> memories."""
        seed_entities = self._resolve_seed_entities(query_terms, min_heat)
        if not seed_entities:
            return []
        activated = self._propagate_activation(
            seed_entities, decay, threshold, max_depth
        )
        return self._map_entities_to_memories(activated, min_heat, max_results)

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
    ) -> list[tuple[int, float]]:
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
                "SELECT id FROM memories WHERE content LIKE ? "
                "AND heat >= ? AND NOT is_stale LIMIT 20",
                (f"%{name}%", min_heat),
            ).fetchall()
            for mr in mem_rows:
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
        """Stub — sqlite-vec does not support efficient batch embedding fetch."""
        return []

    def get_temporal_co_access(
        self,
        window_hours: float = 2.0,
        min_access: int = 1,
        limit: int = 100,
    ) -> list[tuple[int, int, float]]:
        """Stub — temporal co-access requires PG window functions."""
        return []
