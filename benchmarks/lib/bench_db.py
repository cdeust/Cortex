"""Benchmark database helpers — load data into PG, retrieve, cleanup.

Pure passthrough to the production codebase. Retrieval delegates to
mcp_server.core.pg_recall.recall() — the same function used by the
production recall handler.

Usage:
    with BenchmarkDB() as db:
        db.load_memories(memories)
        results = db.recall(query, top_k=10)
"""

from __future__ import annotations

import os
from typing import Any

from mcp_server.core.pg_recall import recall as pg_recall
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.pg_store import PgMemoryStore


class BenchmarkDB:
    """Thin passthrough to the production PG recall pipeline."""

    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/cortex"
        )
        self._store: PgMemoryStore | None = None
        self._embeddings: EmbeddingEngine | None = None
        self._memory_ids: list[int] = []
        self._content_lookup: dict[int, str] = {}
        self._momentum_state: dict = {"momentum": 0.5}

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
        """Insert memories into PG and return their IDs."""
        assert self._store is not None, "Call open() first"

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
                    "created_at": created if created and created.strip() else None,
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

    # ── Retrieval (delegates to codebase) ─────────────────────────

    def recall(
        self,
        query: str,
        top_k: int = 10,
        domain: str | None = None,
        min_heat: float = 0.01,
        rerank: bool = True,
        rerank_alpha: float = 0.55,
    ) -> list[dict[str, Any]]:
        """Delegate to mcp_server.core.pg_recall.recall()."""
        assert self._store is not None, "Call open() first"
        return pg_recall(
            query=query,
            store=self._store,
            embeddings=self._embeddings,
            top_k=top_k,
            domain=domain,
            min_heat=min_heat,
            rerank=rerank,
            rerank_alpha=rerank_alpha,
            momentum_state=self._momentum_state,
        )

    # ── Cleanup ───────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Remove all memories inserted by this benchmark run."""
        if not self._store or not self._memory_ids:
            return
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
        """Alias for cleanup."""
        self.cleanup()
