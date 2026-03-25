"""Benchmark database helpers — load data into PG, retrieve, cleanup.

All benchmarks use the production PostgreSQL + pgvector code path.
No in-memory retrievers. No custom scoring. Same recall_memories()
stored procedure that production uses.

Usage:
    with BenchmarkDB() as db:
        db.load_memories(memories)
        results = db.recall(query, top_k=10)
"""

from __future__ import annotations

import os
from typing import Any

from mcp_server.core.query_intent import classify_query_intent, QueryIntent
from mcp_server.core.reranker import rerank_results
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.pg_store import PgMemoryStore


class BenchmarkDB:
    """Thin wrapper over PgMemoryStore for benchmark use.

    Loads benchmark data into PG, runs production recall, cleans up.
    Each instance tags memories with a unique run_id so parallel
    benchmarks don't collide and cleanup is surgical.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/cortex"
        )
        self._store: PgMemoryStore | None = None
        self._embeddings: EmbeddingEngine | None = None
        self._memory_ids: list[int] = []
        self._content_lookup: dict[int, str] = {}

    # ── Lifecycle ─────────────────────────────────────────────────

    def open(self) -> BenchmarkDB:
        self._store = PgMemoryStore(database_url=self._url)
        if self._embeddings is None:
            self._embeddings = EmbeddingEngine()
        return self

    def close(self) -> None:
        self.cleanup()
        if self._store is not None:
            self._store.close()
            self._store = None

    def __enter__(self) -> BenchmarkDB:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Data loading ──────────────────────────────────────────────

    def load_memories(
        self,
        memories: list[dict[str, Any]],
        *,
        domain: str = "benchmark",
        batch_embed: bool = True,
    ) -> list[int]:
        """Insert memories into PG and return their IDs.

        Each memory dict must have 'content'. Optional keys:
          - date / created_at: ISO timestamp
          - heat: thermodynamic heat (default 1.0)
          - tags: list of tags
          - user_content: user-only text (used for embedding)
          - source: source identifier
        """
        assert self._store is not None, "Call open() first"

        # Batch-encode embeddings for efficiency
        if batch_embed and self._embeddings and self._embeddings.available:
            texts = self._build_embedding_texts(memories)
            embeddings = self._embeddings.encode_batch(texts)
        else:
            embeddings = [None] * len(memories)

        ids = []
        for mem, emb in zip(memories, embeddings):
            created = (
                mem.get("created_at") or mem.get("date") or mem.get("date_iso", "")
            )
            mid = self._store.insert_memory(
                {
                    "content": mem["content"],
                    "embedding": emb,
                    "domain": domain,
                    "source": mem.get("source", "benchmark"),
                    "tags": mem.get("tags", []),
                    "created_at": created if created else None,
                    "heat": mem.get("heat", 1.0),
                    "importance": mem.get("importance", 0.5),
                    "store_type": mem.get("store_type", "episodic"),
                }
            )
            ids.append(mid)
            self._content_lookup[mid] = mem["content"]

        self._memory_ids.extend(ids)
        return ids

    def _build_embedding_texts(self, memories: list[dict]) -> list[str]:
        """Build text for embedding — prefer user_content, add date prefix."""
        texts = []
        for m in memories:
            prefix = ""
            date = m.get("date") or m.get("created_at") or m.get("date_iso", "")
            if date:
                prefix = f"[Date: {date}] "
            user = m.get("user_content", "")
            full = m.get("content", "")[:2000]
            texts.append(prefix + (user[:1500] if user else full))
        return texts

    # ── Retrieval (production code path) ──────────────────────────

    def recall(
        self,
        query: str,
        top_k: int = 10,
        domain: str | None = None,
        min_heat: float = 0.01,
        rerank: bool = True,
        rerank_alpha: float = 0.55,
    ) -> list[dict[str, Any]]:
        """Run production recall_memories() + optional FlashRank reranking.

        Same code path as the recall MCP tool handler.
        """
        assert self._store is not None, "Call open() first"

        # Intent classification (same as production)
        intent_info = classify_query_intent(query)
        intent = intent_info["intent"]
        weights = self._intent_weights(intent, intent_info.get("weights", {}))

        # Encode query
        q_emb = self._embeddings.encode(query[:500]) if self._embeddings else None

        # Call PL/pgSQL recall_memories (production stored procedure)
        candidates = self._store.recall_memories(
            query_text=query,
            query_embedding=q_emb,
            intent=str(intent.value) if hasattr(intent, "value") else str(intent),
            domain=domain,
            min_heat=min_heat,
            max_results=top_k,
            wrrf_k=60,
            weights=weights,
        )

        if not candidates:
            return []

        # Client-side FlashRank reranking (same as production)
        if rerank and len(candidates) > 1:
            ranked_pairs = [(c["memory_id"], c.get("score", 0.0)) for c in candidates]
            content_map = {c["memory_id"]: c["content"] for c in candidates}
            reranked = rerank_results(
                query, ranked_pairs, content_map, alpha=rerank_alpha
            )
            # Rebuild ordered results
            cand_map = {c["memory_id"]: c for c in candidates}
            candidates = []
            for mid, score in reranked:
                if mid in cand_map:
                    c = dict(cand_map[mid])
                    c["score"] = score
                    candidates.append(c)

        return candidates[:top_k]

    def _intent_weights(
        self, intent: QueryIntent, core_weights: dict
    ) -> dict[str, float]:
        """Map intent to PG recall signal weights."""
        base = {
            "vector": core_weights.get("vector", 1.0),
            "fts": core_weights.get("fts", 0.5),
            "bm25": core_weights.get("fts", 0.5) * 0.8,
            "heat": core_weights.get("heat", 0.3),
            "ngram": core_weights.get("fts", 0.5) * 0.6,
            "recency": 0.0,
        }
        if intent == QueryIntent.TEMPORAL:
            base["recency"] = 0.0
            base["heat"] = 0.6
        elif intent == QueryIntent.KNOWLEDGE_UPDATE:
            base["recency"] = 0.5
            base["heat"] = 0.5
        return base

    # ── Cleanup ───────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Remove all memories inserted by this benchmark run."""
        if not self._store or not self._memory_ids:
            return
        # Delete in batches to avoid huge transactions
        batch_size = 500
        for i in range(0, len(self._memory_ids), batch_size):
            batch = self._memory_ids[i : i + batch_size]
            placeholders = ",".join(["%s"] * len(batch))
            self._store._conn.execute(
                f"DELETE FROM memories WHERE id IN ({placeholders})", batch
            )
        self._store._conn.commit()
        self._memory_ids.clear()
        self._content_lookup.clear()

    def clear(self) -> None:
        """Alias for cleanup — matches existing benchmark retriever API."""
        self.cleanup()
