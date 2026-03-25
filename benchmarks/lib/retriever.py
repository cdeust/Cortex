"""Unified benchmark retriever with multi-signal fusion and reranking.

Combines: vector similarity + BM25 + n-gram + temporal proximity
         + RRF fusion + FlashRank ONNX reranking + recency decay
         + critical mass quality zones.

All benchmarks should use this as their retrieval engine.
"""

from __future__ import annotations

import re

from mcp_server.core.scoring import (
    compute_bm25_scores,
    compute_keyword_overlap,
    compute_ngram_score,
)
from mcp_server.core.temporal import (
    compute_date_distance_score,
    compute_recency_boost,
    compute_temporal_proximity,
    extract_date_hints,
)
from mcp_server.core.query_intent import classify_query_intent, QueryIntent
from benchmarks.lib.fusion import (
    QualityZone,
    assess_quality_zone,
    enforce_chunk_limit,
    wrrf_fuse,
)


class BenchmarkRetriever:
    """Production-quality retriever for all benchmarks."""

    def __init__(self, max_results: int = 15):
        self.documents: list[dict] = []
        self._embeddings: list | None = None
        self._emb_engine = None
        self._flashrank = None
        self._max_results = enforce_chunk_limit(max_results)

    def clear(self):
        self.documents = []
        self._embeddings = None

    def add_documents(self, docs: list[dict]):
        self.documents = docs

    # ── Lazy initialization ──────────────────────────────────────────

    def _ensure_embeddings(self):
        if self._embeddings is not None:
            return
        try:
            from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

            if self._emb_engine is None:
                self._emb_engine = EmbeddingEngine()
            if not self._emb_engine.available:
                self._embeddings = []
                return
            texts = self._build_embedding_texts()
            self._embeddings = self._emb_engine.encode_batch(texts)
        except Exception:
            self._embeddings = []

    def _build_embedding_texts(self) -> list[str]:
        texts = []
        for d in self.documents:
            prefix = f"[Date: {d['date']}] " if d.get("date") else ""
            user = d.get("user_content", "")
            full = d.get("content", "")[:2000]
            texts.append(prefix + (user if user else full))
        return texts

    def _ensure_reranker(self):
        if self._flashrank is not None:
            return
        try:
            from flashrank import Ranker

            self._flashrank = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
        except Exception:
            pass

    # ── Signal computation ───────────────────────────────────────────

    def _score_vector(self, query: str) -> list[tuple[int, float]]:
        if not self._embeddings or not self._emb_engine:
            return []
        q_emb = self._emb_engine.encode(query[:500])
        if not q_emb:
            return []
        scored = []
        for i, emb in enumerate(self._embeddings):
            if emb is not None:
                sim = max(0.0, self._emb_engine.similarity(q_emb, emb))
                scored.append((i, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _score_keyword(self, query: str) -> list[tuple[int, float]]:
        scores = [
            (i, compute_keyword_overlap(query, d.get("content", "")))
            for i, d in enumerate(self.documents)
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def _score_ngram(self, query: str) -> list[tuple[int, float]]:
        scores = [
            (i, compute_ngram_score(query, d.get("content", "")))
            for i, d in enumerate(self.documents)
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def _score_bm25(self, query: str) -> list[tuple[int, float]]:
        docs = [d.get("content", "") for d in self.documents]
        bm25 = compute_bm25_scores(query, docs)
        scores = [(i, s) for i, s in enumerate(bm25)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def _score_temporal(self, date_hints: list[str]) -> list[tuple[int, float]]:
        scores = []
        for i, d in enumerate(self.documents):
            # String proximity (existing)
            text_score = compute_temporal_proximity(d.get("content", ""), date_hints)
            # Date distance (new — exponential decay)
            doc_date = (
                d.get("date") or d.get("time_anchor") or d.get("created_at") or ""
            )
            dist_score = compute_date_distance_score(doc_date, date_hints)
            # Combined: max of both signals
            scores.append((i, max(text_score, dist_score)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    # ── Reranking ────────────────────────────────────────────────────

    def _rerank(
        self,
        query: str,
        candidates: list[tuple[int, float]],
        alpha: float = 0.55,
    ) -> list[tuple[int, float]]:
        self._ensure_reranker()
        if not self._flashrank or not candidates:
            return candidates
        try:
            from flashrank import RerankRequest

            passages = [
                {"id": i, "text": self.documents[doc_id]["content"][:1200]}
                for i, (doc_id, _) in enumerate(candidates)
            ]
            req = RerankRequest(query=query, passages=passages)
            results = self._flashrank.rerank(req)
            score_map = {r["id"]: r["score"] for r in results}
            reranked = []
            for i, (doc_id, wrrf_score) in enumerate(candidates):
                ce = score_map.get(i, 0.0)
                reranked.append((doc_id, (1 - alpha) * wrrf_score + alpha * ce))
            reranked.sort(key=lambda x: x[1], reverse=True)
            return reranked
        except Exception:
            return candidates

    # ── Main retrieve ────────────────────────────────────────────────

    def _score_recency_rank(self) -> list[tuple[int, float]]:
        """Score documents by position: later = higher (for knowledge updates)."""
        n = len(self.documents)
        if n == 0:
            return []
        scores = [(i, i / max(n - 1, 1)) for i in range(n)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def retrieve(self, query: str, top_k: int = 10) -> list[dict]:
        """Multi-signal retrieval with RRF fusion and reranking.

        Uses core Cortex query_router for intent classification — same
        logic as production recall handler.
        """
        self._ensure_embeddings()
        if not self.documents:
            return []

        # Use core Cortex intent classification
        intent_info = classify_query_intent(query)
        intent = intent_info["intent"]

        temporal = intent == QueryIntent.TEMPORAL
        date_hints = extract_date_hints(query) if temporal else []
        is_update = intent == QueryIntent.KNOWLEDGE_UPDATE

        # Compute all signals
        signals: dict[str, list[tuple[int, float]]] = {
            "vector": self._score_vector(query),
            "keyword": self._score_keyword(query),
            "ngram": self._score_ngram(query),
            "bm25": self._score_bm25(query),
        }
        if temporal and date_hints:
            signals["temporal"] = self._score_temporal(date_hints)
        if is_update:
            signals["recency"] = self._score_recency_rank()

        # Intent-aware weights from core router
        core_weights = intent_info.get("weights", {})
        # Map core weight keys to benchmark signal names
        weights = {
            "vector": core_weights.get("vector", 1.0),
            "keyword": core_weights.get("fts", 0.5) * 0.8,  # FTS ≈ keyword
            "ngram": core_weights.get("fts", 0.5) * 0.7,
            "bm25": core_weights.get("fts", 0.5) * 0.6,
        }
        if temporal:
            weights["temporal"] = core_weights.get("temporal", 0.8)
        if is_update:
            weights["recency"] = core_weights.get("heat", 0.5)

        fused = wrrf_fuse(signals, weights, k=60)

        # Rerank top candidates
        candidates = self._rerank(query, fused[: top_k * 3])

        # Apply recency boost
        boosted = []
        for doc_id, score in candidates:
            created = self.documents[doc_id].get("date") or self.documents[doc_id].get(
                "created_at"
            )
            boost = compute_recency_boost(created)
            boosted.append((doc_id, score * (1.0 + boost)))
        boosted.sort(key=lambda x: x[1], reverse=True)

        # Enforce limit and build results
        safe_k = enforce_chunk_limit(top_k, self._max_results)
        seen: set[int] = set()
        results = []
        for doc_id, score in boosted:
            if doc_id not in seen:
                seen.add(doc_id)
                result = dict(self.documents[doc_id])
                result["score"] = score
                result["_idx"] = doc_id
                results.append(result)
            if len(results) >= safe_k:
                break
        return results

    # ── Multi-hop with quality gating ────────────────────────────────

    def retrieve_multihop(
        self,
        query: str,
        top_k: int = 10,
        max_hops: int = 2,
        quality_drop_threshold: float = 0.7,
    ) -> list[dict]:
        """Quality-gated multi-hop (ai-architect CoTRAGMultiHopExecutor).

        Stops when quality drops >30% or critical mass reached.
        """
        hop1 = self.retrieve(query, top_k=top_k)
        if not hop1:
            return hop1

        last_quality = _avg_score(hop1)
        all_results = {r["_idx"]: r for r in hop1}

        for _ in range(1, max_hops):
            if assess_quality_zone(len(all_results)) in (
                QualityZone.CRITICAL,
                QualityZone.FAILED,
            ):
                break

            bridges = _extract_bridge_entities(query, all_results)
            if not bridges:
                break

            hop_query = query + " " + " ".join(list(bridges)[:3])
            hop_results = self.retrieve(hop_query, top_k=top_k // 2)
            if not hop_results:
                break

            hop_quality = _avg_score(hop_results)
            if hop_quality < last_quality * quality_drop_threshold:
                break

            for r in hop_results:
                idx = r["_idx"]
                if idx in all_results:
                    all_results[idx]["score"] += r["score"] * 0.3
                else:
                    all_results[idx] = r
            last_quality = hop_quality

        sorted_results = sorted(
            all_results.values(), key=lambda r: r["score"], reverse=True
        )
        return sorted_results[: enforce_chunk_limit(top_k, self._max_results)]


def _avg_score(results: list[dict]) -> float:
    return sum(r["score"] for r in results) / len(results) if results else 0.0


def _extract_bridge_entities(query: str, results: dict[int, dict]) -> set[str]:
    """Find entities in results that aren't in the query."""
    bridge = set()
    for r in list(results.values())[:5]:
        names = re.findall(
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b",
            r.get("content", ""),
        )
        bridge.update(names[:3])
    query_names = set(re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", query))
    return bridge - query_names
