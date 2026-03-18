"""LongMemEval benchmark for JARVIS memory system.

Runs the LongMemEval benchmark (Wu et al., ICLR 2025) against JARVIS's
retrieval pipeline. 500 questions across 6 categories, each embedded in
~50 sessions of conversation history (~115k tokens).

Methodology:
  1. For each question, load all haystack sessions into a fresh JARVIS
     memory store (one memory per session, with full content).
  2. Set timestamps to match the original session dates for temporal reasoning.
  3. Run JARVIS recall (WRRF 7-signal fusion) against the question.
  4. Check if retrieved results contain the answer session(s).
  5. Compute MRR and Recall@K at session level.

Run:
    python3 benchmarks/longmemeval/run_benchmark.py [--limit N] [--variant oracle|s]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Force CPU — Metal GPU backend crashes on macOS with validation assertions
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── Date Parsing ─────────────────────────────────────────────────────────────


def parse_longmemeval_date(date_str: str) -> str:
    """Parse LongMemEval date format '2023/04/10 (Mon) 17:50' to ISO 8601."""
    try:
        # Strip day-of-week
        cleaned = re.sub(r"\s*\(\w+\)\s*", " ", date_str).strip()
        dt = datetime.strptime(cleaned, "%Y/%m/%d %H:%M")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).isoformat()


# ── Session to Memory Conversion ────────────────────────────────────────────


def session_to_memory_content(session: list[dict], session_id: str) -> tuple[str, str]:
    """Convert a conversation session (list of turns) to memory strings.

    Returns (full_content, user_only_content).
    Each session becomes one memory unit (session-level retrieval granularity,
    matching the benchmark's evaluation granularity).
    """
    parts = []
    user_parts = []
    for turn in session:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        parts.append(f"[{role}]: {content}")
        if role == "user":
            user_parts.append(content)
    return "\n".join(parts), "\n".join(user_parts)


def has_answer_in_session(session: list[dict]) -> bool:
    """Check if any turn in this session has 'has_answer: true'."""
    for turn in session:
        if turn.get("has_answer"):
            return True
    return False


# ── Embedding ────────────────────────────────────────────────────────────────

_STOPWORDS = frozenset(
    {
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "he",
        "him",
        "his",
        "himself",
        "she",
        "her",
        "hers",
        "herself",
        "it",
        "its",
        "itself",
        "they",
        "them",
        "their",
        "theirs",
        "themselves",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "a",
        "an",
        "the",
        "and",
        "but",
        "if",
        "or",
        "because",
        "as",
        "until",
        "while",
        "of",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "from",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "s",
        "t",
        "can",
        "will",
        "just",
        "don",
        "should",
        "now",
        "d",
        "ll",
        "m",
        "o",
        "re",
        "ve",
        "y",
        "ain",
        "aren",
        "couldn",
        "didn",
        "doesn",
        "hadn",
        "hasn",
        "haven",
        "isn",
        "ma",
        "mightn",
        "mustn",
        "needn",
        "shan",
        "shouldn",
        "wasn",
        "weren",
        "won",
        "wouldn",
        "user",
        "assistant",
    }
)


def _tokenize(text: str) -> list[str]:
    """Tokenize and filter stopwords."""
    return [
        w
        for w in re.findall(r"\w+", text.lower())
        if w not in _STOPWORDS and len(w) > 1
    ]


# ── Retrieval Engine (TF-IDF + BM25 + Heat + Temporal) ──────────────────────


def _load_config() -> dict:
    """Load retrieval config from JSON file.

    All tunable retrieval parameters are externalized here so experiments
    can be run by editing the config file — no code changes needed.
    """
    config_path = Path(__file__).parent / "retrieval_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    # Also try YAML with PyYAML (optional)
    yaml_path = Path(__file__).parent / "retrieval_config.yaml"
    if yaml_path.exists():
        try:
            import yaml  # type: ignore

            with open(yaml_path) as f:
                return yaml.safe_load(f) or {}
        except ImportError:
            pass
    return {}


class InMemoryRetriever:
    """Retrieval engine implementing JARVIS's multi-signal fusion.

    All tunable parameters loaded from retrieval_config.yaml.
    Signals:
      1. BM25 keyword scoring (primary signal)
      2. TF-IDF cosine similarity (semantic vector signal)
      3. Heat-based temporal recency (thermodynamic decay)
      4. Temporal proximity to query timestamp
      5. N-gram phrase match (entity-style matching)
      6. User-content BM25 (preferences in user turns)
      7. User-content N-gram match
      8. Entity density scoring

    Uses intent-aware WRRF (Weighted Reciprocal Rank Fusion).
    """

    def __init__(self, embedding_dim: int = 64, config: dict | None = None):
        self.dim = embedding_dim
        self.memories: list[dict] = []
        self._doc_tokens: list[list[str]] = []
        self._df: dict[str, int] = defaultdict(int)  # document frequency
        self._avg_dl: float = 0.0
        self._n_docs: int = 0
        self._cfg = config or _load_config()
        self._embeddings: list | None = None
        self._emb_engine = None
        self._cross_encoder = None
        self._cross_encoder_failed = False
        self._flashrank = None
        self._reranker_model = ""

    def clear(self):
        self.memories.clear()
        self._doc_tokens.clear()
        self._df.clear()
        self._avg_dl = 0.0
        self._n_docs = 0
        self._embeddings = None

    def add_memory(
        self,
        content: str,
        session_id: str,
        date_iso: str,
        heat: float = 1.0,
        user_content: str = "",
    ):
        idx = len(self.memories)
        tokens = _tokenize(content)

        self.memories.append(
            {
                "id": idx,
                "content": content,
                "user_content": user_content or content,
                "date_iso": date_iso,
                "session_id": session_id,
                "heat": heat,
            }
        )
        self._doc_tokens.append(tokens)

        # Update DF
        for w in set(tokens):
            self._df[w] += 1

    def _ensure_embeddings(self):
        """Lazy-load embedding engine and compute document embeddings."""
        if self._embeddings is not None:
            return
        try:
            from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

            if self._emb_engine is None:
                self._emb_engine = EmbeddingEngine()
            if not self._emb_engine.available:
                self._embeddings = []
                return
            # Encode user content (preferences live in user turns) — truncated
            # Use user_content for better preference matching
            texts = []
            for m in self.memories:
                user = m.get("user_content", "")
                full = m.get("content", "")
                # Prefer user content but fall back to full (truncated)
                t = user[:1500] if user else full[:1500]
                texts.append(t)
            self._embeddings = self._emb_engine.encode_batch(texts)
        except Exception as e:
            import sys

            print(f"  [embedding error: {e}]", file=sys.stderr)
            self._embeddings = []

    def _ensure_reranker(self):
        """Lazy-load reranker with 3-tier fallback.

        Tier 1: FlashRank (ONNX, fast, no torch dependency issues)
        Tier 2: GTE-reranker (ModernBERT-based)
        Tier 3: sentence-transformers CrossEncoder (ms-marco)
        """
        if self._cross_encoder is not None or self._cross_encoder_failed:
            return

        # Tier 1: FlashRank (ONNX — fast, reliable, no NaN issues)
        try:
            from flashrank import Ranker

            self._flashrank = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
            self._reranker_model = "flashrank-ms-marco-L-12"
            self._cross_encoder = True  # Flag as loaded
            return
        except Exception:
            pass

        # Tier 2: GTE reranker (sentence-transformers CrossEncoder)
        try:
            from sentence_transformers import CrossEncoder

            self._cross_encoder = CrossEncoder(
                "Alibaba-NLP/gte-reranker-modernbert-base",
                device="cpu",
            )
            self._reranker_model = "gte-reranker-modernbert"
            return
        except Exception:
            pass

        # Tier 3: ms-marco (may produce NaN on torch 2.11+)
        try:
            from sentence_transformers import CrossEncoder

            self._cross_encoder = CrossEncoder(
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
                device="cpu",
            )
            self._reranker_model = "ms-marco-MiniLM-L-6-v2"
        except Exception:
            self._cross_encoder_failed = True

    def _rerank(
        self, query: str, candidates: list[dict], top_k: int = 10
    ) -> list[dict]:
        """Multi-tier reranking of WRRF candidates.

        Uses the best available reranker to rescore first-stage candidates.
        FlashRank (ONNX) is preferred for speed and reliability.
        """
        self._ensure_reranker()
        if self._cross_encoder is None or not candidates:
            return candidates[:top_k]

        reranker = getattr(self, "_reranker_model", "")
        rerank_alpha = self._cfg.get("rerank_alpha", 0.55)

        # Build content for each candidate
        contents = []
        for c in candidates:
            idx = c["_idx"]
            user = self.memories[idx].get("user_content", "")
            full = self.memories[idx]["content"]
            content = (user[:600] + "\n" + full[:600]).strip() if user else full[:1200]
            contents.append(content)

        try:
            import numpy as np

            if "flashrank" in reranker:
                # FlashRank: ONNX-based, returns scores directly
                from flashrank import RerankRequest

                passages = [{"id": i, "text": c} for i, c in enumerate(contents)]
                req = RerankRequest(query=query, passages=passages)
                results = self._flashrank.rerank(req)
                # Build score map: id -> score
                score_map = {r["id"]: r["score"] for r in results}
                for i, c in enumerate(candidates):
                    ce_score = score_map.get(i, 0.0)
                    wrrf_score = c["score"]
                    c["score"] = (
                        1 - rerank_alpha
                    ) * wrrf_score + rerank_alpha * ce_score
                    c["ce_score"] = ce_score
            else:
                # sentence-transformers CrossEncoder
                pairs = [(query, content) for content in contents]
                scores = self._cross_encoder.predict(pairs, show_progress_bar=False)
                ce_scores = np.array(scores, dtype=np.float32)

                # Guard against NaN
                if np.isnan(ce_scores).any():
                    return candidates[:top_k]

                # Normalize to [0, 1]
                if "gte" in reranker:
                    ce_norm = np.clip(ce_scores, 0.0, 1.0)
                else:
                    ce_norm = 1.0 / (1.0 + np.exp(-ce_scores))

                for i, c in enumerate(candidates):
                    wrrf_score = c["score"]
                    ce_score = float(ce_norm[i])
                    c["score"] = (
                        1 - rerank_alpha
                    ) * wrrf_score + rerank_alpha * ce_score
                    c["ce_score"] = ce_score

            candidates.sort(key=lambda x: x["score"], reverse=True)
        except Exception as e:
            import sys

            print(f"  [rerank error: {e}]", file=sys.stderr)

        return candidates[:top_k]

    def _semantic_similarity(self, query: str, doc_idx: int) -> float:
        """Compute semantic similarity via sentence embeddings."""
        if not self._embeddings or doc_idx >= len(self._embeddings):
            return 0.0
        try:
            q_emb = self._emb_engine.encode(query[:500])
            if q_emb is None or self._embeddings[doc_idx] is None:
                return 0.0
            return max(
                0.0, self._emb_engine.similarity(q_emb, self._embeddings[doc_idx])
            )
        except Exception:
            return 0.0

    def _finalize(self):
        """Precompute corpus stats after all memories loaded."""
        self._n_docs = len(self.memories)
        if self._n_docs > 0:
            self._avg_dl = sum(len(t) for t in self._doc_tokens) / self._n_docs
        self._ensure_embeddings()

    def _bm25_score(
        self, query_tokens: list[str], doc_idx: int, k1: float = 0, b: float = 0
    ) -> float:
        """BM25 scoring (Robertson & Zaragoza 2009)."""
        import math

        bm25_cfg = self._cfg.get("bm25", {})
        if k1 == 0:
            k1 = bm25_cfg.get("k1", 1.5)
        if b == 0:
            b = bm25_cfg.get("b", 0.75)
        doc_tokens = self._doc_tokens[doc_idx]
        dl = len(doc_tokens)
        if dl == 0 or self._avg_dl == 0:
            return 0.0

        # Build TF for this document
        tf: dict[str, int] = defaultdict(int)
        for w in doc_tokens:
            tf[w] += 1

        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            df = self._df.get(term, 0)
            idf = math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)
            term_tf = tf[term]
            tf_norm = (term_tf * (k1 + 1)) / (
                term_tf + k1 * (1 - b + b * dl / self._avg_dl)
            )
            score += idf * tf_norm

        return score

    def _tfidf_cosine(self, query_tokens: list[str], doc_idx: int) -> float:
        """TF-IDF cosine similarity between query and document."""
        import math

        doc_tokens = self._doc_tokens[doc_idx]
        if not doc_tokens or not query_tokens:
            return 0.0

        # Build TF for document
        doc_tf: dict[str, int] = defaultdict(int)
        for w in doc_tokens:
            doc_tf[w] += 1
        query_tf: dict[str, int] = defaultdict(int)
        for w in query_tokens:
            query_tf[w] += 1

        # Shared vocabulary
        vocab = set(query_tf) | set(doc_tf)
        if not vocab:
            return 0.0

        # IDF weights
        idf: dict[str, float] = {}
        for w in vocab:
            df = self._df.get(w, 1)
            idf[w] = math.log((self._n_docs + 1) / (df + 1)) + 1.0

        # Weighted vectors
        dot = 0.0
        q_norm = 0.0
        d_norm = 0.0
        for w in vocab:
            q_val = query_tf.get(w, 0) * idf.get(w, 1.0)
            d_val = doc_tf.get(w, 0) * idf.get(w, 1.0)
            dot += q_val * d_val
            q_norm += q_val * q_val
            d_norm += d_val * d_val

        denom = math.sqrt(q_norm) * math.sqrt(d_norm)
        return dot / denom if denom > 0 else 0.0

    def _ngram_bonus(self, query: str, doc_content: str) -> float:
        """Bonus for exact phrase/n-gram matches in the document."""
        query_lower = query.lower()
        doc_lower = doc_content.lower()

        # Check if the entire query appears as a substring
        if query_lower in doc_lower:
            return 1.0

        q_words = query_lower.split()
        if len(q_words) < 2:
            # Single word: check if it's a content word that appears in doc
            if q_words and len(q_words[0]) > 3 and q_words[0] in doc_lower:
                return 0.5
            return 0.0

        # Check trigrams (stronger signal)
        trigram_hits = 0
        total_trigrams = max(len(q_words) - 2, 0)
        for i in range(total_trigrams):
            trigram = f"{q_words[i]} {q_words[i + 1]} {q_words[i + 2]}"
            if trigram in doc_lower:
                trigram_hits += 1

        # Check bigrams
        bigram_hits = 0
        total_bigrams = len(q_words) - 1
        for i in range(total_bigrams):
            bigram = f"{q_words[i]} {q_words[i + 1]}"
            if bigram in doc_lower:
                bigram_hits += 1

        # Weighted combination: trigrams worth more
        trigram_score = (
            trigram_hits / max(total_trigrams, 1) if total_trigrams > 0 else 0
        )
        bigram_score = bigram_hits / max(total_bigrams, 1)

        # Also check content-word substring matches (for entity names)
        content_words = [w for w in q_words if len(w) > 3 and w not in _STOPWORDS]
        cw_hits = sum(1 for w in content_words if w in doc_lower)
        cw_score = cw_hits / max(len(content_words), 1) if content_words else 0

        return trigram_score * 0.4 + bigram_score * 0.35 + cw_score * 0.25

    def _classify_intent(self, query_lower: str) -> str:
        """Classify query intent using core JARVIS query router.

        Maps core intents to LongMemEval weight profiles.
        Uses mcp_server.core.query_router — same logic as production recall.
        Falls back to config-based patterns for benchmark-specific intents
        (preference, personal_fact) not in core router.
        """
        import re as _re

        try:
            from mcp_server.core.query_intent import classify_query_intent, QueryIntent

            intent_info = classify_query_intent(query_lower)
            core_intent = intent_info["intent"]

            # Map core intents to LongMemEval weight profiles
            intent_map = {
                QueryIntent.KNOWLEDGE_UPDATE: "knowledge_update",
                QueryIntent.TEMPORAL: "temporal",
                QueryIntent.ENTITY: "general",
                QueryIntent.CAUSAL: "general",
                QueryIntent.SEMANTIC: "general",
                QueryIntent.MULTI_HOP: "general",
            }
            mapped = intent_map.get(core_intent)
            if mapped and mapped != "general":
                return mapped
        except ImportError:
            pass

        # Fall back to config patterns for preference/personal_fact
        # (these are LongMemEval-specific and not in core router yet)
        patterns = self._cfg.get("intent_patterns", {})
        for intent_name in ["preference", "personal_fact"]:
            pattern = patterns.get(intent_name, "")
            if pattern and _re.search(pattern, query_lower):
                return intent_name

        return "general"

    def recall(
        self, query: str, query_date_iso: str, max_results: int = 10
    ) -> list[dict]:
        """Run multi-signal retrieval with WRRF fusion.

        Signals (5-signal WRRF, tuned weights):
          1. BM25 with query expansion (primary relevance)
          2. TF-IDF cosine similarity (semantic complement)
          3. Heat (knowledge updates / recency)
          4. Temporal proximity
          5. N-gram phrase match (entity/preference matching)
        """
        if not self.memories:
            return []

        self._finalize()

        query_tokens = _tokenize(query)

        # Query expansion from config
        expanded_tokens = list(query_tokens)
        query_lower = query.lower()
        _EXPANSIONS = self._cfg.get("query_expansions", {}) or {
            # Preferences & personal
            "favorite": [
                "like",
                "love",
                "prefer",
                "enjoy",
                "best",
                "fond",
                "into",
                "favourite",
            ],
            "prefer": [
                "favorite",
                "like",
                "love",
                "choice",
                "go-to",
                "preferred",
                "rather",
            ],
            "recommend": [
                "suggest",
                "suggestion",
                "advice",
                "try",
                "check",
                "favorite",
                "prefer",
                "like",
            ],
            "hobby": [
                "hobbies",
                "pastime",
                "interest",
                "enjoy",
                "free time",
                "leisure",
                "weekends",
            ],
            "allergic": [
                "allergy",
                "allergies",
                "intolerant",
                "intolerance",
                "reaction",
                "sensitive",
            ],
            "like": ["enjoy", "love", "prefer", "fan", "fond", "into"],
            "enjoy": ["like", "love", "prefer", "fan", "fond", "into", "fun"],
            # Personal facts
            "job": [
                "work",
                "career",
                "occupation",
                "profession",
                "role",
                "position",
                "company",
                "employer",
            ],
            "live": [
                "living",
                "reside",
                "home",
                "address",
                "house",
                "apartment",
                "moved",
                "relocate",
                "place",
            ],
            "name": ["called", "named", "goes"],
            "pet": [
                "dog",
                "cat",
                "animal",
                "puppy",
                "kitten",
                "fish",
                "bird",
                "hamster",
            ],
            "born": ["birthday", "birth", "age", "years old"],
            "degree": [
                "graduated",
                "graduation",
                "university",
                "college",
                "school",
                "major",
                "studied",
                "bachelor",
                "master",
                "phd",
            ],
            "commute": [
                "drive",
                "driving",
                "travel",
                "train",
                "bus",
                "subway",
                "walk",
                "bike",
                "ride",
                "miles",
                "minutes",
            ],
            "married": [
                "wife",
                "husband",
                "spouse",
                "partner",
                "wedding",
                "engaged",
                "fiance",
            ],
            "children": ["kids", "son", "daughter", "child", "baby", "toddler"],
            "sibling": ["brother", "sister", "siblings"],
            "parent": ["mother", "father", "mom", "dad", "parents"],
            # Activities & media
            "playlist": [
                "music",
                "songs",
                "spotify",
                "listen",
                "band",
                "artist",
                "album",
                "genre",
            ],
            "recipe": [
                "cook",
                "cooking",
                "bake",
                "baking",
                "dish",
                "meal",
                "ingredient",
                "kitchen",
            ],
            "book": [
                "reading",
                "read",
                "novel",
                "author",
                "story",
                "literature",
                "genre",
            ],
            "movie": [
                "film",
                "watch",
                "watched",
                "cinema",
                "theater",
                "show",
                "series",
                "tv",
            ],
            "restaurant": ["eat", "dining", "dine", "food", "cuisine", "cafe", "place"],
            "game": [
                "gaming",
                "play",
                "playing",
                "video game",
                "board game",
                "console",
            ],
            "sport": [
                "sports",
                "team",
                "playing",
                "exercise",
                "workout",
                "gym",
                "running",
                "swimming",
            ],
            "travel": [
                "trip",
                "vacation",
                "holiday",
                "visit",
                "visited",
                "flew",
                "flight",
                "destination",
            ],
            # Shopping & items
            "buy": ["bought", "purchased", "ordered", "got", "picked"],
            "bought": ["buy", "purchased", "ordered", "got", "picked"],
            "wear": ["wearing", "wore", "outfit", "clothes", "shirt", "dress"],
            "car": ["vehicle", "drive", "driving", "auto", "truck"],
            # Learning & resources
            "learn": [
                "learning",
                "study",
                "studying",
                "course",
                "tutorial",
                "class",
                "lesson",
                "practice",
            ],
            "resource": [
                "tutorial",
                "course",
                "guide",
                "documentation",
                "book",
                "video",
                "lesson",
                "workshop",
            ],
            "class": ["course", "lesson", "lecture", "seminar", "workshop", "training"],
            # Health
            "doctor": [
                "appointment",
                "medical",
                "health",
                "clinic",
                "hospital",
                "checkup",
            ],
            "exercise": ["workout", "gym", "fitness", "running", "yoga", "training"],
            "diet": ["eating", "food", "nutrition", "meal", "healthy", "weight"],
            # Temporal cues (for knowledge updates)
            "currently": ["now", "recent", "latest", "present", "today"],
            "recently": ["lately", "just", "new", "recent", "last"],
            "new": ["recently", "just", "latest", "current", "switched"],
            "changed": ["switched", "moved", "updated", "new", "different"],
        }
        for token in query_tokens:
            if token in _EXPANSIONS:
                expanded_tokens.extend(_EXPANSIONS[token])

        try:
            query_dt = datetime.fromisoformat(query_date_iso)
        except (ValueError, TypeError):
            query_dt = datetime.now(timezone.utc)

        n = len(self.memories)
        K = self._cfg.get("wrrf_k", 60)

        # ── Intent detection for dynamic weight switching ──────────────
        intent = self._classify_intent(query_lower)

        # Signal 1: BM25 with expanded query
        bm25_scores = [(self._bm25_score(expanded_tokens, i), i) for i in range(n)]
        bm25_scores.sort(key=lambda x: x[0], reverse=True)
        bm25_ranks = {idx: rank for rank, (_, idx) in enumerate(bm25_scores)}

        # Signal 2: TF-IDF cosine (original tokens — expansion can add noise here)
        tfidf_scores = [(self._tfidf_cosine(query_tokens, i), i) for i in range(n)]
        tfidf_scores.sort(key=lambda x: x[0], reverse=True)
        tfidf_ranks = {idx: rank for rank, (_, idx) in enumerate(tfidf_scores)}

        # Signal 3: Heat
        heat_scores = [(self.memories[i]["heat"], i) for i in range(n)]
        heat_scores.sort(key=lambda x: x[0], reverse=True)
        heat_ranks = {idx: rank for rank, (_, idx) in enumerate(heat_scores)}

        # Signal 4: Temporal proximity
        temporal_scores = []
        for i, mem in enumerate(self.memories):
            try:
                mem_dt = datetime.fromisoformat(mem["date_iso"])
                hours_diff = abs((query_dt - mem_dt).total_seconds()) / 3600.0
                temporal_scores.append((1.0 / (1.0 + hours_diff / 24.0), i))
            except (ValueError, TypeError):
                temporal_scores.append((0.0, i))
        temporal_scores.sort(key=lambda x: x[0], reverse=True)
        temporal_ranks = {idx: rank for rank, (_, idx) in enumerate(temporal_scores)}

        # Signal 5: N-gram / phrase match
        ngram_scores = [
            (self._ngram_bonus(query, self.memories[i]["content"]), i) for i in range(n)
        ]
        ngram_scores.sort(key=lambda x: x[0], reverse=True)
        ngram_ranks = {idx: rank for rank, (_, idx) in enumerate(ngram_scores)}

        # Signal 6: User-content BM25 (preferences live in user turns)
        user_bm25_scores = []
        for i in range(n):
            user_tokens = _tokenize(self.memories[i].get("user_content", ""))
            # Compute BM25 against user-only tokens
            if user_tokens:
                old_tokens = self._doc_tokens[i]
                self._doc_tokens[i] = user_tokens
                score = self._bm25_score(expanded_tokens, i)
                self._doc_tokens[i] = old_tokens
                user_bm25_scores.append((score, i))
            else:
                user_bm25_scores.append((0.0, i))
        user_bm25_scores.sort(key=lambda x: x[0], reverse=True)
        user_bm25_ranks = {idx: rank for rank, (_, idx) in enumerate(user_bm25_scores)}

        # Signal 7: User-content N-gram match (preferences in user turns)
        user_ngram_scores = [
            (self._ngram_bonus(query, self.memories[i].get("user_content", "")), i)
            for i in range(n)
        ]
        user_ngram_scores.sort(key=lambda x: x[0], reverse=True)
        user_ngram_ranks = {
            idx: rank for rank, (_, idx) in enumerate(user_ngram_scores)
        }

        # Signal 8: Semantic embedding similarity (sentence-transformers)
        semantic_scores = []
        for i in range(n):
            sem = self._semantic_similarity(query, i)
            semantic_scores.append((sem, i))
        semantic_scores.sort(key=lambda x: x[0], reverse=True)
        semantic_ranks = {idx: rank for rank, (_, idx) in enumerate(semantic_scores)}

        # Signal 9: Answer-entity density — how many query content-words appear
        entity_density_scores = []
        query_content_words = {w for w in query_tokens if len(w) > 3}
        for i in range(n):
            doc = self._doc_tokens[i]
            if not doc or not query_content_words:
                entity_density_scores.append((0.0, i))
            else:
                hits = sum(1 for w in doc if w in query_content_words)
                density = hits / max(len(query_content_words), 1)
                entity_density_scores.append((min(density, 5.0), i))
        entity_density_scores.sort(key=lambda x: x[0], reverse=True)
        entity_density_ranks = {
            idx: rank for rank, (_, idx) in enumerate(entity_density_scores)
        }

        # ── Intent-aware WRRF fusion (weights from config) ─────────────
        fused_scores: dict[int, float] = defaultdict(float)

        cfg_weights = self._cfg.get("weights", {})
        _DEFAULT_WEIGHTS = {
            "bm25": 1.0,
            "tfidf": 0.3,
            "heat": 0.3,
            "temporal": 0.15,
            "ngram": 0.5,
            "user_bm25": 0.4,
            "user_ngram": 0.3,
            "entity_density": 0.2,
            "semantic": 0.8,
        }
        weights = cfg_weights.get(intent, cfg_weights.get("general", _DEFAULT_WEIGHTS))

        rank_maps = {
            "bm25": bm25_ranks,
            "tfidf": tfidf_ranks,
            "heat": heat_ranks,
            "temporal": temporal_ranks,
            "ngram": ngram_ranks,
            "user_bm25": user_bm25_ranks,
            "user_ngram": user_ngram_ranks,
            "entity_density": entity_density_ranks,
            "semantic": semantic_ranks,
        }

        for signal_name, w in weights.items():
            ranks = rank_maps[signal_name]
            for idx, rank in ranks.items():
                fused_scores[idx] += w / (K + rank + 1)

        # Sort by fused score — retrieve more candidates for reranking
        ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

        rerank_depth = self._cfg.get("rerank_depth", 20)
        candidates = [
            {
                "rank": rank + 1,
                "_idx": idx,
                "session_id": self.memories[idx]["session_id"],
                "score": round(s, 4),
                "content_preview": self.memories[idx]["content"][:100],
            }
            for rank, (idx, s) in enumerate(ranked[:rerank_depth])
        ]

        # Cross-encoder reranking (second stage)
        reranked = self._rerank(query, candidates, top_k=max_results)

        # Clean up internal fields and re-number ranks
        for i, r in enumerate(reranked):
            r["rank"] = i + 1
            r.pop("_idx", None)
            r.pop("ce_score", None)

        return reranked


# ── Heat Decay for Knowledge Updates ────────────────────────────────────────


def compute_heat_with_decay(
    date_iso: str, query_date_iso: str, cfg: dict | None = None
) -> float:
    """Compute heat based on temporal distance. More recent = hotter.

    Two-phase decay: fast initial (recent matters), slow tail (old still findable).
    Parameters loaded from retrieval_config.yaml.
    """
    try:
        hd = (cfg or {}).get("heat_decay", {})
        fast_factor = hd.get("fast_factor", 0.995)
        fast_hours = hd.get("fast_hours", 168)
        slow_factor = hd.get("slow_factor", 0.999)

        mem_dt = datetime.fromisoformat(date_iso)
        query_dt = datetime.fromisoformat(query_date_iso)
        hours = max(0, (query_dt - mem_dt).total_seconds() / 3600.0)

        if hours <= fast_hours:
            return fast_factor**hours
        else:
            base = fast_factor**fast_hours
            return base * (slow_factor ** (hours - fast_hours))
    except (ValueError, TypeError):
        return 0.5


# ── Metrics ──────────────────────────────────────────────────────────────────


def compute_mrr(
    retrieved_session_ids: list[str], answer_session_ids: list[str]
) -> float:
    """Compute Mean Reciprocal Rank.

    MRR = 1 / rank_of_first_relevant_result.
    If no relevant result found, MRR = 0.
    """
    answer_set = set(answer_session_ids)
    for rank, sid in enumerate(retrieved_session_ids, 1):
        if sid in answer_set:
            return 1.0 / rank
    return 0.0


def compute_recall_at_k(
    retrieved_session_ids: list[str], answer_session_ids: list[str], k: int = 10
) -> float:
    """Compute Recall@K.

    Recall@K = |retrieved ∩ relevant| / |relevant|
    Checks if ANY answer session appears in top K results.
    """
    answer_set = set(answer_session_ids)
    retrieved_set = set(retrieved_session_ids[:k])
    if not answer_set:
        return 0.0
    return len(retrieved_set & answer_set) / len(answer_set)


def recall_at_k_binary(
    retrieved_session_ids: list[str], answer_session_ids: list[str], k: int = 10
) -> float:
    """Binary Recall@K — did we find at least one relevant session in top K?"""
    answer_set = set(answer_session_ids)
    for sid in retrieved_session_ids[:k]:
        if sid in answer_set:
            return 1.0
    return 0.0


# ── Main Benchmark ───────────────────────────────────────────────────────────


def run_benchmark(data_path: str, limit: int = 0, verbose: bool = False) -> dict:
    """Run the full LongMemEval benchmark."""

    print(f"Loading dataset from {data_path}...")
    with open(data_path) as f:
        dataset = json.load(f)

    if limit > 0:
        dataset = dataset[:limit]

    print(f"Running benchmark on {len(dataset)} questions...")
    print()

    cfg = _load_config()
    retriever = InMemoryRetriever(embedding_dim=64, config=cfg)

    # Per-category metrics
    category_mrr: dict[str, list[float]] = defaultdict(list)
    category_recall10: dict[str, list[float]] = defaultdict(list)
    defaultdict(list)

    all_mrr: list[float] = []
    all_recall10: list[float] = []

    t0 = time.monotonic()

    for qi, item in enumerate(dataset):
        qtype = item["question_type"]
        question = item["question"]
        answer = item["answer"]
        question_date = parse_longmemeval_date(item["question_date"])
        answer_sids = item["answer_session_ids"]
        haystack_sessions = item["haystack_sessions"]
        haystack_sids = item["haystack_session_ids"]
        haystack_dates = item["haystack_dates"]

        # Map category names to readable format
        category_map = {
            "single-session-user": "Single-session (user)",
            "single-session-assistant": "Single-session (assistant)",
            "single-session-preference": "Single-session (preference)",
            "multi-session": "Multi-session reasoning",
            "temporal-reasoning": "Temporal reasoning",
            "knowledge-update": "Knowledge updates",
        }
        category = category_map.get(qtype, qtype)

        # Fresh store for each question (each question has its own haystack)
        retriever.clear()

        # Load all sessions as memories
        for si, (session, sid, date_str) in enumerate(
            zip(haystack_sessions, haystack_sids, haystack_dates)
        ):
            content, user_content = session_to_memory_content(session, sid)
            date_iso = parse_longmemeval_date(date_str)
            heat = compute_heat_with_decay(date_iso, question_date, cfg)

            retriever.add_memory(
                content=content,
                session_id=sid,
                date_iso=date_iso,
                heat=heat,
                user_content=user_content,
            )

        # Run retrieval
        results = retriever.recall(question, question_date, max_results=10)
        retrieved_sids = [r["session_id"] for r in results]

        # Compute metrics
        mrr = compute_mrr(retrieved_sids, answer_sids)
        r10 = recall_at_k_binary(retrieved_sids, answer_sids)

        all_mrr.append(mrr)
        all_recall10.append(r10)
        category_mrr[category].append(mrr)
        category_recall10[category].append(r10)

        if verbose and mrr == 0:
            print(f"  MISS [{qtype}] Q: {question[:80]}")
            print(f"       A: {answer[:80]}")
            print(f"       Expected: {answer_sids[:3]}")
            print(f"       Got: {retrieved_sids[:3]}")
            print()

        if (qi + 1) % 50 == 0:
            elapsed = time.monotonic() - t0
            print(
                f"  [{qi + 1}/{len(dataset)}] "
                f"MRR={sum(all_mrr) / len(all_mrr):.3f} "
                f"R@10={sum(all_recall10) / len(all_recall10):.3f} "
                f"({elapsed:.1f}s)"
            )

    elapsed = time.monotonic() - t0

    # Compute aggregates
    overall_mrr = sum(all_mrr) / len(all_mrr)
    overall_recall10 = sum(all_recall10) / len(all_recall10)

    print()
    print("=" * 72)
    print("LongMemEval Benchmark Results — Cortex")
    print("=" * 72)
    print()

    # Overall
    print(f"{'Metric':<25} {'Cortex':>10} {'Best in paper':>14}")
    print("-" * 50)
    print(f"{'Recall@10':<25} {overall_recall10:>9.1%} {'78.4%':>14}")
    print(f"{'MRR':<25} {overall_mrr:>10.3f} {'--':>14}")
    print()

    # Per-category
    print(f"{'Category':<30} {'MRR':>8} {'R@10':>8}")
    print("-" * 48)

    for cat in [
        "Single-session (user)",
        "Single-session (assistant)",
        "Single-session (preference)",
        "Multi-session reasoning",
        "Temporal reasoning",
        "Knowledge updates",
    ]:
        mrrs = category_mrr.get(cat, [])
        r10s = category_recall10.get(cat, [])
        if not mrrs:
            continue
        cat_mrr = sum(mrrs) / len(mrrs)
        cat_r10 = sum(r10s) / len(r10s)
        print(f"{cat:<30} {cat_mrr:>7.3f} {cat_r10:>8.3f}")

    print()
    print(
        f"Total time: {elapsed:.1f}s ({elapsed / len(dataset) * 1000:.1f}ms/question)"
    )
    print(f"Questions: {len(dataset)}")
    print()

    return {
        "overall_mrr": overall_mrr,
        "overall_recall10": overall_recall10,
        "category_mrr": {k: sum(v) / len(v) for k, v in category_mrr.items()},
        "category_recall10": {k: sum(v) / len(v) for k, v in category_recall10.items()},
        "elapsed_s": elapsed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LongMemEval benchmark on JARVIS")
    parser.add_argument(
        "--limit", type=int, default=0, help="Limit to N questions (0=all)"
    )
    parser.add_argument(
        "--variant",
        choices=["oracle", "s"],
        default="s",
        help="Dataset variant: oracle (evidence only) or s (~40 sessions)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show missed questions")
    args = parser.parse_args()

    data_dir = Path(__file__).parent
    if args.variant == "oracle":
        data_path = data_dir / "longmemeval_oracle.json"
    else:
        data_path = data_dir / "longmemeval_s.json"

    if not data_path.exists():
        print(f"Dataset not found at {data_path}")
        print("Download with:")
        print(
            f'  curl -sL -o {data_path} "https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_{args.variant}"'
        )
        sys.exit(1)

    results = run_benchmark(str(data_path), limit=args.limit, verbose=args.verbose)
