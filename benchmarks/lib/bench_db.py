"""Benchmark database helpers — load data into PG, retrieve, cleanup.

Pure passthrough to the production codebase. Ingestion uses
mcp_server.core.memory_ingest, retrieval uses mcp_server.core.pg_recall.
bench_db holds zero business logic.

Usage:
    with BenchmarkDB() as db:
        db.load_memories(memories)
        results = db.recall(query, top_k=10)
"""

from __future__ import annotations

import os
from typing import Any

from mcp_server.core.memory_ingest import ingest_memories_batch
from mcp_server.core.pg_recall import recall as pg_recall
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.pg_store import PgMemoryStore


class BenchmarkDB:
    """Thin passthrough to the production PG pipeline."""

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
        self._purge_stale_benchmark_data()
        if self._embeddings is None:
            self._embeddings = EmbeddingEngine()
        return self

    def _purge_stale_benchmark_data(self) -> None:
        """Remove orphaned benchmark memories from crashed/killed runs."""
        assert self._store is not None
        self._store._execute("DELETE FROM memories WHERE is_benchmark = TRUE")
        self._store._conn.commit()

    def close(self) -> None:
        self.cleanup()
        if self._store is not None:
            self._store.close()
            self._store = None

    def __enter__(self) -> BenchmarkDB:
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── Data loading (delegates to codebase) ──────────────────────

    def load_memories(
        self,
        memories: list[dict[str, Any]],
        *,
        domain: str = "benchmark",
        batch_embed: bool = True,
        decompose: bool = True,
    ) -> tuple[list[int], dict[int, str]]:
        """Delegate to mcp_server.core.memory_ingest.ingest_memories_batch().

        Returns (ids, source_map) where source_map maps memory_id → source string.
        """
        assert self._store is not None, "Call open() first"
        ids, source_map = ingest_memories_batch(
            memories,
            self._store,
            self._embeddings if batch_embed else None,
            domain=domain,
            decompose=decompose,
            is_benchmark=True,
        )
        self._memory_ids.extend(ids)
        return ids, source_map

    # ── Retrieval (delegates to codebase) ─────────────────────────

    def recall(
        self,
        query: str,
        top_k: int = 10,
        domain: str | None = None,
        agent_topic: str | None = None,
        min_heat: float = 0.01,
        rerank: bool = True,
        rerank_alpha: float = 0.70,
    ) -> list[dict[str, Any]]:
        """Delegate to mcp_server.core.pg_recall.recall()."""
        assert self._store is not None, "Call open() first"
        return pg_recall(
            query=query,
            store=self._store,
            embeddings=self._embeddings,
            top_k=top_k,
            domain=domain,
            agent_topic=agent_topic,
            min_heat=min_heat,
            rerank=rerank,
            rerank_alpha=rerank_alpha,
            momentum_state=self._momentum_state,
            include_globals=False,
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
