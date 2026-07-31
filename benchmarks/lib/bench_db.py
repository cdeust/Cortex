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
from typing import Any, Callable

from mcp_server.core.memory_ingest import ingest_memories_batch
from mcp_server.core.pg_recall import (
    assemble_context as pg_assemble_context,
    recall as pg_recall,
)
from mcp_server.core.reranker import ensure_reranker_loaded
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine
from mcp_server.infrastructure.pg_store import PgMemoryStore


class BenchmarkDB:
    """Thin passthrough to the production PG pipeline.

    on_connection_open: optional callback(connection) invoked once after
    the underlying psycopg connection is created. Used by the ablation
    runner to apply deterministic per-session GUCs (playbook §8). Must
    NOT be wired in production callers — this is benchmark-only.

    require_reranker: when True, ``open()`` fails fast (RuntimeError) if
    the FlashRank cross-encoder is not loaded, instead of silently
    scoring first-stage-only results as if they were production quality.
    Fix for the 2026-07-10 incident (see mcp_server.core.reranker module
    docstring): a bare-except swallow in the reranker singleton let 6
    LongMemEval runs execute — and get reported — with reranking silently
    disabled (MRR 0.9163 -> 0.8636, no signal anywhere in the run).
    Production-parity harnesses (LongMemEval, LoCoMo, BEAM — the ones
    reproduce.sh gates against published floors) must set this True.
    Harnesses that intentionally test a mechanism in isolation (e.g.
    gate_precision) leave it False.

    INC7.2 audit (2026-07-11) of every ``BenchmarkDB(...)`` call site under
    ``benchmarks/`` — which ones claim production parity and therefore need
    ``require_reranker=True``:

    Enabled by this audit (each claims a falsifiable/production-fidelity
    result that a silently-degraded first-stage-only pipeline would
    corrupt — see the inline comment at each call site for the specific
    claim):
      - benchmarks/lib/e2_subsample_runner.py  (E2 claim-bearing retrieval)
      - benchmarks/lib/e2_zipf_runner.py        (E2 claim-bearing retrieval)
      - benchmarks/lib/latency_runner.py        (production wall-time claim)
      - benchmarks/beam/ablation.py             (sweeps rerank_alpha itself)
      - benchmarks/lib/_xb_drivers.py           (sweeps FlashRank top-K)

    Reviewed and left False (documented, not an oversight):
      - benchmarks/gate_precision/run_benchmark.py — measures the write
        gate's novelty score (evaluate_gate), never calls recall/rerank;
        the reranker is not in this harness's dependency graph at all.
      - benchmarks/locomo/run_benchmark_agents.py — self-declared "NOT an
        official benchmark" (module docstring); compares scoped vs
        unscoped retrieval against EACH OTHER, so the reranker's
        load-state is a constant nuisance factor across both arms, not a
        differential bias.
      - benchmarks/lib/longitudinal_runner.py — diagnostic decay-pipeline
        harness, not falsifiability-registered or reproduce.sh-gated;
        borderline case, flagged for a future increment to reconsider.
      - benchmarks/llm_head_to_head/pilot.py — Stage-1 dry-run stress test
        (module docstring: "not load-bearing for the GO/NO-GO gate"); its
        live-mode B condition calls the real
        ``mcp_server.handlers.recall.handler`` (production entrypoint,
        already reranker-aware), not a bare ``BenchmarkDB.recall`` — the
        ``BenchmarkDB()`` instance at this call site is only used for
        memory seeding, not scored retrieval.
      - benchmarks/spell_alteration/run_benchmark.py — standalone
        user-invoked script (requires a ``--pdf`` path arg), not part of
        any automated gate; recall-quality claims are informal.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        on_connection_open: Callable[[Any], None] | None = None,
        require_reranker: bool = False,
    ) -> None:
        self._url = database_url or os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/cortex"
        )
        self._store: PgMemoryStore | None = None
        self._embeddings: EmbeddingEngine | None = None
        self._memory_ids: list[int] = []
        self._content_lookup: dict[int, str] = {}
        self._momentum_state: dict = {"momentum": 0.5}
        self._on_connection_open = on_connection_open
        self._require_reranker = require_reranker

    # ── Lifecycle ─────────────────────────────────────────────────

    def open(self) -> BenchmarkDB:
        if self._require_reranker:
            status = ensure_reranker_loaded()
            if status.state != "loaded":
                raise RuntimeError(
                    "BenchmarkDB(require_reranker=True): FlashRank reranker "
                    f"is NOT loaded (state={status.state!r}, "
                    f"model_path={status.model_path!r}"
                    + (f", error={status.error!r}" if status.error else "")
                    + "). Refusing to run a production-parity benchmark "
                    "against a first-stage-only retrieval pipeline — this "
                    "is exactly the silent-skip that cost the 2026-07-10 "
                    "MRR regression (0.9163 -> 0.8636) undetected across 6 "
                    "runs. Fix the reranker load (see mcp_server.core."
                    "reranker module docstring) before retrying."
                )
        self._store = PgMemoryStore(database_url=self._url)
        # Auto-apply deterministic session when the runner has set the env
        # var (playbook §8); benchmarks/lib/ablation_runner sets it per row.
        run_id = os.environ.get("CORTEX_BENCH_DETERMINISTIC_RUN_ID")
        if run_id and self._on_connection_open is None:
            from benchmarks.lib import db_setup  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

            db_setup.apply_deterministic_session(self._store._conn, run_id=run_id)
        elif self._on_connection_open is not None:
            self._on_connection_open(self._store._conn)
        self._purge_stale_benchmark_data()
        if self._embeddings is None:
            self._embeddings = EmbeddingEngine()
        return self

    def _require_opened(self) -> None:
        """Raise if ``open()`` hasn't run yet.

        Extracted (TRY003, issue #239 — Extract Function): the 4 call
        sites below each repeated this exact guard+message; this is now
        the one place that constructs it. ``self._store`` itself is
        still read at each call site (not returned here) since this
        directory is excluded from the pyright gate (pyrightconfig.json)
        and every call site already narrows via its own `is None` check
        pattern used elsewhere in this class.
        """
        if self._store is None:
            raise AssertionError("Call open() first")  # noqa: TRY003 — canonical, 4-call-site-shared construction point (§3.3); see docstring above

    def _purge_stale_benchmark_data(self) -> None:
        """Remove orphaned benchmark memories from crashed/killed runs."""
        self._require_opened()
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
        self._require_opened()
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
        self._require_opened()
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

    def assemble_context(
        self,
        query: str,
        *,
        current_stage: str,
        token_budget: int | None = None,
        domain: str | None = "beam",
        stage_field: str = "agent_context",
        budget_split: tuple[float, float, float] = (0.6, 0.3, 0.1),
        max_chunks_per_phase: int = 5,
        stage_detector: Any | None = None,
    ) -> dict[str, Any]:
        """Delegate to mcp_server.core.pg_recall.assemble_context().

        Returns the structured 3-phase context dict (see pg_recall
        for the schema). The benchmark uses ``selected_memories`` to
        compute retrieval hit ranks.
        """
        self._require_opened()
        return pg_assemble_context(
            query=query,
            store=self._store,
            embeddings=self._embeddings,
            current_stage=current_stage,
            token_budget=token_budget,
            domain=domain,
            stage_field=stage_field,
            budget_split=budget_split,
            max_chunks_per_phase=max_chunks_per_phase,
            stage_detector=stage_detector,
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
                f"DELETE FROM memories WHERE id IN ({placeholders})",  # noqa: S608 — interpolation is a generated ?/%s placeholder list; every value is a bound parameter (docs/ASSURANCE-CASE.md §5)
                batch,
            )
        self._store._conn.commit()
        self._memory_ids.clear()
        self._content_lookup.clear()

    def clear(self) -> None:
        """Alias for cleanup."""
        self.cleanup()
