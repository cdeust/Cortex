"""LoCoMo retriever with 3-tier dispatch.

Tier 1 — Simple: fast inline keyword+vector+BM25+ngram+temporal+FlashRank.
Tier 2 — Mixed: entity-bridged multi-hop with sub-query decomposition.
Tier 3 — Deep: full BM25+ngram for factual/instruction queries.

Dispatch based on complexity + factual density scoring.
Temporal: proper date parsing + exponential decay distance scoring.
Multi-hop: query decomposition + entity bridging (HippoRAG-inspired).
Knowledge: entity-attribute supersession for knowledge update queries.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import datetime

from mcp_server.core.scoring import compute_bm25_scores, compute_ngram_score
from mcp_server.core.query_intent import classify_query_intent, QueryIntent


class LoCoMoRetriever:
    """3-tier dispatch retriever using core JARVIS query routing.

    Uses mcp_server.core.query_router for intent detection — same logic
    as production recall handler. Benchmark-specific adaptations only for
    in-memory document scoring (vs SQLite in production).
    """

    _DATE_EXTRACT_RE = re.compile(
        r"\[Date:\s*([^\]]+)\]|"
        r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{4})|"
        r"(\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    )

    _MONTH_MAP = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    def __init__(self):
        self.sessions: list[dict] = []
        self._embeddings = None
        self._emb_engine = None
        self._flashrank = None
        self._bm25_cache: list[str] | None = None
        self._session_dates: list[datetime | None] = []

    def clear(self):
        self.sessions = []
        self._embeddings = None
        self._bm25_cache = None
        self._session_dates = []

    def add_sessions(self, sessions: list[dict]):
        self.sessions = sessions
        self._bm25_cache = [s["content"] for s in sessions]
        self._session_dates = [self._parse_date(s.get("date", "")) for s in sessions]

    # ── Lazy init ────────────────────────────────────────────────

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
            texts = []
            for s in self.sessions:
                user = s.get("user_content", "")
                full = s["content"][:2000]
                prefix = f"[Date: {s['date']}] " if s.get("date") else ""
                texts.append(prefix + (user if user else full))
            self._embeddings = self._emb_engine.encode_batch(texts)
        except Exception as e:
            print(f"  [embedding error: {e}]", file=sys.stderr)
            self._embeddings = []

    def _ensure_reranker(self):
        if self._flashrank is not None:
            return
        try:
            from flashrank import Ranker

            self._flashrank = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
        except Exception:
            pass

    # ── Date parsing ─────────────────────────────────────────────

    def _parse_date(self, date_str: str) -> datetime | None:
        """Parse various date formats to datetime."""
        if not date_str:
            return None
        date_str = date_str.strip()
        # Try ISO format
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00").split("T")[0])
        except (ValueError, AttributeError):
            pass
        # Try "DD Month YYYY" or "Month DD, YYYY"
        m = re.match(
            r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{4})",
            date_str,
            re.IGNORECASE,
        )
        if m:
            try:
                return datetime(
                    int(m.group(3)),
                    self._MONTH_MAP[m.group(2).lower()],
                    int(m.group(1)),
                )
            except (ValueError, KeyError):
                pass
        m = re.match(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})",
            date_str,
            re.IGNORECASE,
        )
        if m:
            try:
                return datetime(
                    int(m.group(3)),
                    self._MONTH_MAP[m.group(1).lower()],
                    int(m.group(2)),
                )
            except (ValueError, KeyError):
                pass
        # Try extracting any date-like pattern from content
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", date_str)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        return None

    def _parse_query_target_date(
        self, query: str, date_hints: list[str]
    ) -> datetime | None:
        """Extract a target date from query date hints."""
        for hint in date_hints:
            dt = self._parse_date(hint)
            if dt:
                return dt
        return None

    # ── Dispatch via core query_router ──────────────────────────

    def _classify_intent(self, query: str) -> dict:
        """Use core JARVIS query router for intent classification."""
        return classify_query_intent(query)

    def retrieve(self, query: str, top_k: int = 10) -> list[dict]:
        """Route query using core JARVIS intent classification."""
        intent_info = self._classify_intent(query)
        intent = intent_info["intent"]

        if intent == QueryIntent.MULTI_HOP:
            return self._retrieve_multihop(query, top_k)
        elif intent == QueryIntent.ENTITY:
            return self._retrieve_deep(query, top_k)
        return self._retrieve_inline(query, top_k, intent_info=intent_info)

    # ── Tier 1: Simple inline retrieval ──────────────────────────

    def _retrieve_inline(
        self,
        query: str,
        top_k: int = 10,
        intent_info: dict | None = None,
    ) -> list[dict]:
        self._ensure_embeddings()
        if intent_info is None:
            intent_info = self._classify_intent(query)
        intent = intent_info["intent"]
        is_temporal = intent == QueryIntent.TEMPORAL
        date_hints = self._extract_date_hints(query) if is_temporal else []
        is_update = intent == QueryIntent.KNOWLEDGE_UPDATE

        scores = {
            i: {
                "vector": 0.0,
                "keyword": 0.0,
                "ngram": 0.0,
                "bm25": 0.0,
                "temporal": 0.0,
                "temporal_dist": 0.0,
                "recency": 0.0,
            }
            for i in range(len(self.sessions))
        }

        # Vector similarity
        if self._embeddings and self._emb_engine:
            q_emb = self._emb_engine.encode(query[:500])
            if q_emb:
                for i, emb in enumerate(self._embeddings):
                    if emb is not None:
                        scores[i]["vector"] = max(
                            0.0, self._emb_engine.similarity(q_emb, emb)
                        )

        # Keyword overlap
        query_terms = set(re.findall(r"\w+", query.lower()))
        for i, s in enumerate(self.sessions):
            doc_terms = set(re.findall(r"\w+", s["content"].lower()))
            if query_terms:
                scores[i]["keyword"] = len(query_terms & doc_terms) / len(query_terms)

        # N-gram phrase matching
        for i, s in enumerate(self.sessions):
            scores[i]["ngram"] = compute_ngram_score(query, s["content"])

        # BM25 scoring
        if self._bm25_cache:
            bm25_scores = compute_bm25_scores(query, self._bm25_cache)
            for i, bm25 in enumerate(bm25_scores):
                scores[i]["bm25"] = bm25

        # Temporal scoring: hint matching + date distance
        if is_temporal and date_hints:
            target_date = self._parse_query_target_date(query, date_hints)
            for i, s in enumerate(self.sessions):
                scores[i]["temporal"] = self._compute_temporal_score(s, date_hints)
                if target_date and self._session_dates[i]:
                    scores[i]["temporal_dist"] = self._compute_date_distance_score(
                        self._session_dates[i], target_date
                    )

        # Recency boost for knowledge update queries
        if is_update:
            for i, dt in enumerate(self._session_dates):
                scores[i]["recency"] = self._compute_recency_rank(i)

        # Intent-aware weights
        if is_temporal:
            w = {
                "vector": 0.4,
                "keyword": 0.2,
                "ngram": 0.2,
                "bm25": 0.3,
                "temporal": 0.8,
                "temporal_dist": 0.6,
                "recency": 0.0,
            }
        elif is_update:
            w = {
                "vector": 0.8,
                "keyword": 0.4,
                "ngram": 0.3,
                "bm25": 0.3,
                "temporal": 0.0,
                "temporal_dist": 0.0,
                "recency": 0.5,
            }
        else:
            w = {
                "vector": 1.0,
                "keyword": 0.5,
                "ngram": 0.4,
                "bm25": 0.3,
                "temporal": 0.0,
                "temporal_dist": 0.0,
                "recency": 0.0,
            }

        candidates = [
            {"_idx": i, "score": sum(w.get(k, 0) * v for k, v in sig.items())}
            for i, sig in scores.items()
        ]
        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = candidates[: top_k * 3]

        candidates = self._rerank(query, candidates)
        return self._build_results(candidates, top_k)

    # ── Tier 2: Multi-hop retrieval ──────────────────────────────

    def _retrieve_multihop(self, query: str, top_k: int = 10) -> list[dict]:
        """Multi-hop with query decomposition + entity bridging."""
        # Step 1: decompose query into sub-queries
        sub_queries = self._decompose_query(query)

        all_results: dict[int, float] = {}

        # Step 2: full query retrieval
        for r in self._retrieve_inline(query, top_k=top_k):
            all_results[r["session_idx"]] = max(
                all_results.get(r["session_idx"], 0), r["score"]
            )

        # Step 3: per-entity sub-queries
        for sub_q in sub_queries:
            for r in self._retrieve_inline(sub_q, top_k=top_k // 2):
                idx = r["session_idx"]
                all_results[idx] = all_results.get(idx, 0) + r["score"] * 0.3

        # Step 4: entity bridging — extract entities from top results
        #         that are NOT in the query → second hop
        top_session_ids = sorted(all_results, key=all_results.get, reverse=True)[:5]
        bridge_entities = self._extract_bridge_entities(query, top_session_ids)

        for entity in bridge_entities[:3]:
            for r in self._retrieve_inline(entity, top_k=top_k // 3):
                idx = r["session_idx"]
                # Bridged results get bonus if they also appeared in hop-1
                bonus = 0.4 if idx in all_results else 0.2
                all_results[idx] = all_results.get(idx, 0) + r["score"] * bonus

        sorted_results = sorted(all_results.items(), key=lambda x: x[1], reverse=True)
        results = []
        for session_idx, score in sorted_results[:top_k]:
            session = next(
                (s for s in self.sessions if s["session_idx"] == session_idx), None
            )
            if session:
                results.append(
                    {
                        "session_idx": session_idx,
                        "content": session["content"],
                        "score": score,
                    }
                )
        return results

    # ── Tier 3: Deep BM25 retrieval ──────────────────────────────

    def _retrieve_deep(self, query: str, top_k: int = 10) -> list[dict]:
        """Deep BM25+ngram retrieval for factual/instruction queries."""
        self._ensure_embeddings()

        scores = {
            i: {"bm25": 0.0, "ngram": 0.0, "keyword": 0.0, "vector": 0.0}
            for i in range(len(self.sessions))
        }

        # Primary signal: BM25
        if self._bm25_cache:
            bm25_scores = compute_bm25_scores(query, self._bm25_cache)
            for i, bm25 in enumerate(bm25_scores):
                scores[i]["bm25"] = bm25

        # N-gram phrase matching
        for i, s in enumerate(self.sessions):
            scores[i]["ngram"] = compute_ngram_score(query, s["content"])

        # Keyword overlap
        query_terms = set(re.findall(r"\w+", query.lower()))
        for i, s in enumerate(self.sessions):
            doc_terms = set(re.findall(r"\w+", s["content"].lower()))
            if query_terms:
                scores[i]["keyword"] = len(query_terms & doc_terms) / len(query_terms)

        # Vector as secondary
        if self._embeddings and self._emb_engine:
            q_emb = self._emb_engine.encode(query[:500])
            if q_emb:
                for i, emb in enumerate(self._embeddings):
                    if emb is not None:
                        scores[i]["vector"] = max(
                            0.0, self._emb_engine.similarity(q_emb, emb)
                        )

        w = {"bm25": 1.0, "ngram": 0.6, "keyword": 0.4, "vector": 0.5}

        candidates = [
            {"_idx": i, "score": sum(w.get(k, 0) * v for k, v in sig.items())}
            for i, sig in scores.items()
        ]
        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = candidates[: top_k * 3]

        candidates = self._rerank(query, candidates)
        return self._build_results(candidates, top_k)

    # ── Query decomposition ──────────────────────────────────────

    def _decompose_query(self, query: str) -> list[str]:
        """Split multi-entity queries into sub-queries."""
        # Extract named entities
        entities = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", query)
        entities = list(dict.fromkeys(e for e in entities if len(e) > 2))

        sub_queries = []
        for entity in entities[:4]:
            sub_queries.append(entity)

        # Also extract quoted phrases
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
        for q in quoted:
            phrase = q[0] or q[1]
            if phrase and phrase not in sub_queries:
                sub_queries.append(phrase)

        return sub_queries

    def _extract_bridge_entities(
        self, query: str, top_session_ids: list[int]
    ) -> list[str]:
        """Find entities in top results that aren't in the query."""
        query_entities = set(
            e.lower()
            for e in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", query)
        )
        bridge = []
        for sid in top_session_ids:
            session = next((s for s in self.sessions if s["session_idx"] == sid), None)
            if not session:
                continue
            names = re.findall(
                r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", session["content"]
            )
            for name in names[:5]:
                if name.lower() not in query_entities and name not in bridge:
                    bridge.append(name)
        return bridge[:5]

    # ── Temporal helpers ─────────────────────────────────────────

    def _extract_date_hints(self, query: str) -> list[str]:
        hints = []
        for m in self._DATE_EXTRACT_RE.finditer(query):
            hint = m.group(1) or m.group(2) or m.group(3)
            if hint:
                hints.append(hint.strip())
        months = re.findall(
            r"\b(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\b",
            query,
            re.IGNORECASE,
        )
        hints.extend(months)
        return list(set(hints))

    def _compute_temporal_score(self, session: dict, date_hints: list[str]) -> float:
        """String-based date hint matching (existing logic, still useful)."""
        session_date = session.get("date", "").lower()
        content = session.get("content", "").lower()
        score = 0.0
        for hint in date_hints:
            h = hint.lower()
            if h in session_date:
                score = max(score, 1.0)
            elif h in content:
                score = max(score, 0.7)
            elif any(p in session_date for p in h.split()):
                score = max(score, 0.4)
        return score

    def _compute_date_distance_score(
        self, session_date: datetime, target_date: datetime, scale_days: float = 14.0
    ) -> float:
        """Exponential decay distance: closer dates score higher."""
        delta_days = abs((session_date - target_date).total_seconds()) / 86400.0
        return math.exp(-delta_days / scale_days)

    def _compute_recency_rank(self, idx: int) -> float:
        """Recency score: later sessions score higher (for knowledge update queries)."""
        n = len(self.sessions)
        if n <= 1:
            return 1.0
        return idx / (n - 1)  # 0.0 for first session, 1.0 for last

    # ── Reranking ────────────────────────────────────────────────

    def _rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        self._ensure_reranker()
        if not self._flashrank or not candidates:
            return candidates
        try:
            from flashrank import RerankRequest

            passages = [
                {"id": i, "text": self.sessions[c["_idx"]]["content"][:1200]}
                for i, c in enumerate(candidates)
            ]
            req = RerankRequest(query=query, passages=passages)
            results = self._flashrank.rerank(req)
            score_map = {r["id"]: r["score"] for r in results}
            for i, c in enumerate(candidates):
                ce = score_map.get(i, 0.0)
                c["score"] = 0.45 * c["score"] + 0.55 * ce
            candidates.sort(key=lambda x: x["score"], reverse=True)
        except Exception:
            pass
        return candidates

    def _build_results(self, candidates: list[dict], top_k: int) -> list[dict]:
        seen: set[int] = set()
        results = []
        for c in candidates:
            idx = c["_idx"]
            if idx not in seen:
                seen.add(idx)
                results.append(
                    {
                        "session_idx": self.sessions[idx]["session_idx"],
                        "content": self.sessions[idx]["content"],
                        "score": c["score"],
                    }
                )
            if len(results) >= top_k:
                break
        return results
