"""Memory system configuration — extends Cortex config with thermodynamic
memory settings.

All settings are overridable via CORTEX_MEMORY_ env prefix.
Defaults tuned from production parameters.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

from mcp_server.infrastructure.config import METHODOLOGY_DIR


def _detect_runtime() -> str:
    """Detect runtime environment: 'cli' or 'cowork'."""
    explicit = os.environ.get("CORTEX_RUNTIME", "")
    if explicit in ("cli", "cowork"):
        return explicit
    if os.environ.get("CLAUDE_ENVIRONMENT") == "cowork":
        return "cowork"
    return "cli"


class MemorySettings(BaseSettings):
    """Thermodynamic memory configuration.

    Groups:
      - Storage: SQLite paths and limits
      - Thermodynamics: heat, decay, surprise
      - Retrieval: fusion weights and limits
      - Write gate: predictive coding thresholds
      - Reconsolidation: lability and stability
      - Prospective: trigger limits
      - Hippocampal replay: checkpoint settings
      - Embedding: model and dimensions
    """

    # ── Runtime ──────────────────────────────────────────────────────────
    # "cli" | "cowork" — set by validator from CORTEX_RUNTIME or
    # CLAUDE_ENVIRONMENT
    RUNTIME: str = ""

    # ── Storage ──────────────────────────────────────────────────────────
    # 127.0.0.1 not localhost: avoids IPv6 ::1 / peer-auth ambiguity
    DATABASE_URL: str = "postgresql://127.0.0.1:5432/cortex"
    DB_PATH: str = str(METHODOLOGY_DIR / "memory.db")  # deprecated, kept for migration
    SQLITE_FALLBACK_PATH: str = str(METHODOLOGY_DIR / "memory.db")
    STORE_BACKEND: str = "auto"  # "auto" | "postgresql" | "sqlite"
    SESSION_LOG_ROLLING_LIMIT: int = 1000

    # ── Thermodynamics ────────────────────────────────────────────────────
    DECAY_FACTOR: float = 0.95
    IMPORTANCE_DECAY_FACTOR: float = 0.998
    COLD_THRESHOLD: float = 0.05
    HOT_THRESHOLD: float = 0.7
    SURPRISE_BOOST: float = 0.3
    EMOTIONAL_DECAY_RESISTANCE: float = 0.5
    SYNAPTIC_WINDOW_MINUTES: int = 30
    SYNAPTIC_BOOST: float = 0.2
    SESSION_COHERENCE_BONUS: float = 0.2
    SESSION_COHERENCE_WINDOW_HOURS: float = 4.0

    # ── Retrieval ─────────────────────────────────────────────────────────
    DEFAULT_RECALL_LIMIT: int = 10
    WRRF_K: int = 60
    WRRF_CANDIDATE_MULTIPLIER: int = 10
    WRRF_VECTOR_WEIGHT: float = 1.0
    WRRF_FTS_WEIGHT: float = 0.5
    WRRF_HEAT_WEIGHT: float = 0.3

    # ── Hopfield ──────────────────────────────────────────────────────────
    HOPFIELD_BETA: float = 8.0
    HOPFIELD_MAX_PATTERNS: int = 5000

    # ── Spreading Activation (Collins & Loftus 1975) ────────────────────
    SA_DECAY: float = 0.65
    SA_THRESHOLD: float = 0.1
    SA_MAX_DEPTH: int = 3
    SA_MAX_NODES: int = 50

    # ── Write Gate (Predictive Coding) ────────────────────────────────────
    WRITE_GATE_THRESHOLD: float = 0.4
    WRITE_GATE_CONTINUITY_DISCOUNT: float = 0.15
    WRITE_GATE_CONTINUITY_WINDOW: int = 10
    # Novelty-score source for the write gate. False = flat 4-signal
    # weighted sum (compute_novelty_score); True = 3-level hierarchical
    # free-energy gate (Friston 2005), whose sigmoid novelty_score is on the
    # same [0,1] scale so the threshold/bypass/calibration path is unchanged.
    # Default MUST stay flat: benchmarks/gate_precision (2026-06-11,
    # benchmarks/results/gate_precision/20260611-220728.json) measured
    # ROC-AUC flat 0.9998 vs hierarchical 0.5514 on novel-vs-duplicate
    # separation. Two structural defects in the hierarchical path: (1) the
    # neutral schema default (match=0.0) makes L2 free energy a constant 1.5,
    # flooring the sigmoid score above the 0.4 threshold for ALL content;
    # (2) no level carries embedding-similarity evidence, so duplicates of
    # stored content are invisible to it. Do not flip without redesigning
    # L0/L2 and re-running gate_precision.
    # Toggle: CORTEX_MEMORY_WRITE_GATE_HIERARCHICAL.
    WRITE_GATE_HIERARCHICAL: bool = False

    # ── Reconsolidation ───────────────────────────────────────────────────
    RECONSOLIDATION_LOW_THRESHOLD: float = 0.3
    RECONSOLIDATION_HIGH_THRESHOLD: float = 0.7
    PLASTICITY_SPIKE: float = 0.3
    PLASTICITY_HALF_LIFE_HOURS: float = 6.0
    STABILITY_INCREMENT: float = 0.1

    # ── Engram ────────────────────────────────────────────────────────────
    EXCITABILITY_HALF_LIFE_HOURS: float = 6.0
    EXCITABILITY_BOOST: float = 0.5

    # ── Prospective ───────────────────────────────────────────────────────
    MAX_TRIGGER_FIRES: int = 5

    # ── Hippocampal Replay ────────────────────────────────────────────────
    REPLAY_MAX_RESTORE_MEMORIES: int = 8
    REPLAY_ANCHOR_HEAT: float = 1.0
    REPLAY_CHECKPOINT_AUTO_INTERVAL: int = 50

    # ── Compression ───────────────────────────────────────────────────────
    COMPRESSION_GIST_AGE_HOURS: float = 168.0  # 7 days
    COMPRESSION_TAG_AGE_HOURS: float = 720.0  # 30 days

    # ── Recency Boost (ai-architect inspired) ──────────────────────────────
    RECENCY_BOOST_MAX: float = 0.15  # Maximum recency bonus
    RECENCY_BOOST_HALFLIFE_DAYS: float = 30.0  # Exponential decay half-life
    RECENCY_BOOST_CUTOFF_DAYS: float = 90.0  # No boost after this age

    # ── Strategic Ordering ("Lost in the Middle" mitigation) ─────────────
    STRATEGIC_ORDERING_ENABLED: bool = True
    STRATEGIC_TOP_FRACTION: float = 0.3  # Top 30% at start
    STRATEGIC_BOTTOM_FRACTION: float = 0.2  # Bottom 20% at end

    # ── Test-Time Learning (Titans, NeurIPS 2025) ─────────────────────────
    SURPRISE_MOMENTUM_ENABLED: bool = True
    SURPRISE_MOMENTUM_ETA: float = 0.7  # momentum decay (EMA)
    SURPRISE_MOMENTUM_DELTA: float = 0.08  # max heat change per recall

    # ── Adaptive Decay (Titans, NeurIPS 2025) ────────────────────────────
    ADAPTIVE_DECAY_ENABLED: bool = True
    ADAPTIVE_DECAY_MIN_RATE: float = 0.90
    ADAPTIVE_DECAY_MAX_RATE: float = 0.999

    # ── Co-Activation (Dragon Hatchling, Pathway 2025) ───────────────────
    CO_ACTIVATION_ENABLED: bool = True
    CO_ACTIVATION_LEARNING_RATE: float = 0.1
    CO_ACTIVATION_MIN_SCORE: float = 0.3

    # ── Response budget (bounded MCP I/O) ─────────────────────────────────
    # source: Claude Code 2.1.170 binary, extracted 2026-06-10 —
    # MAX_MCP_OUTPUT_TOKENS default 25000 tokens × 4 chars/token = 100,000
    # chars of compact-JSON payload, × 0.75 safety factor (UTF-16 vs
    # code-point divergence guard, ai-prd-builder ContextManager.swift
    # commit 462de01). Full derivation + char-exact verification:
    # mcp_server/core/response_budget.py module docstring.
    MAX_RESPONSE_CHARS: int = 75_000

    # ── Embedding ─────────────────────────────────────────────────────────
    EMBEDDING_DIM: int = 384
    EMBEDDING_DEVICE: str = "cpu"  # "cpu" | "auto" | "cuda" | "mps"

    # ── A3 lazy-heat (Phase 3 Scalability Program, v3.13.0) ───────────────
    # Kill-switch for the A3 refactor. After the main refactor landed,
    # the Python layer assumes heat_base unconditionally — this flag is
    # reserved for a future DDL-level swap of effective_heat() to
    # effective_heat_frozen() per design doc §9. Kept on the settings
    # object for forward compat with tests that still reference it.
    A3_LAZY_HEAT: bool = True

    # ── Phase 5: ConnectionPool latency classes ───────────────────────────
    # Source: docs/program/phase-5-pool-admission-design.md §1.1.
    #
    # Interactive pool — hot path (recall, remember, anchor, etc.). Sized
    # for concurrent MCP tool invocations. min=2 keeps two connections
    # warm; max=8 ≥ cycle-workers + 1 satisfies invariant I10.
    POOL_INTERACTIVE_MIN: int = 2
    POOL_INTERACTIVE_MAX: int = 8
    POOL_INTERACTIVE_TIMEOUT_S: float = 5.0

    # Batch pool — long-running writers (consolidate, seed_project,
    # wiki_pipeline, ingest_*). Separate resource so batch jobs cannot
    # starve interactive calls.
    POOL_BATCH_MIN: int = 1
    POOL_BATCH_MAX: int = 2
    POOL_BATCH_TIMEOUT_S: float = 1800.0  # 30 min — consolidate can run this long

    # Emergency kill switch: if true, pools are bypassed and every
    # `pool.connection()` returns a single shared connection (pre-Phase-5
    # behavior). Default false post-merge.
    POOL_DISABLED: bool = False

    # ── MCP client pool (bounded-io Phase 3) ─────────────────────────────
    # Max live upstream MCP child connections held in mcp_client_pool. Each
    # pooled connection is a spawned child OS PROCESS (asyncio
    # create_subprocess_exec in mcp_client._spawn_process), not a cheap DB
    # handle, so the binding constraint is OS process / RSS pressure — the
    # exact failure mode in the ingest_codebase ConnectionResetError RCA
    # 2026-06-09 (child driven to OOM). Beyond this count, get_client evicts
    # the least-recently-used IDLE connection before opening a new one, and
    # fails fast with McpConnectionError when all live connections are busy.
    #
    # Default 0 = "derive from os.cpu_count()" (see _resolve_mcp_pool_max):
    # one heavy child process per core is a defensible machine-relative
    # ceiling, floored at 2 so a 1-core box can still hold a working set of
    # two distinct upstream servers. This is an ENGINEERING DEFAULT pending
    # measurement: the value that would truly calibrate it is the measured
    # steady-state RSS of the spawned children (today only `codebase` /
    # automatised-pipeline is heavy) against available host memory. Override
    # via CORTEX_MEMORY_MCP_POOL_MAX_CONNECTIONS once that data exists.
    # source: os.cpu_count() machine bound; floor mirrors a two-server
    # working set; RSS calibration is the open measurement.
    MCP_POOL_MAX_CONNECTIONS: int = 0

    # automatised-pipeline (ADR-0046) — on by default so the L6 symbol
    # ring has depth out of the box. Users who want to cut token /
    # subprocess cost override via CORTEX_MEMORY_AP_ENABLED=0 in their
    # MCP config.
    AP_ENABLED: bool = True

    # Cross-loop wait ceiling (seconds) for the single AP reader thread in
    # workflow_graph_source_ast._SyncLoop. The reader owns one event loop and
    # blocks the caller on future.result(timeout=AP_SYNC_RESULT_TIMEOUT_S).
    # Without it, a wedged AP subprocess (JSON-RPC pipe stalled below the
    # in-loop await) hangs the calling worker forever (Lamport H4: "concurrent
    # reads" over one pipe is an illusion; an untimed .result() never returns).
    #
    # Floor rationale: ap_bridge deliberately sets callTimeoutMs=0, so each AP
    # query runs under mcp_client's no-timeout fallback of 3600 s
    # (mcp_client.py:319 effective_timeout = 3600.0). The CROSS-loop wait must
    # be >= that IN-loop ceiling, or it false-fires on a query the loop still
    # considers alive. We add a 300 s drain margin (mcp_client idle timeout is
    # 300 s, mcp_client.py:41) for the cancellation/error to propagate back
    # across the loop boundary after the in-loop bound trips.
    # source: mcp_client.py:319 (3600 s AP-call ceiling) + mcp_client.py:41
    #   (300 s idle/drain). ENGINEERING DEFAULT pending measurement: calibrate
    #   by measuring p99 wall time of a full load_ast_edges() sweep (89 queries)
    #   on the largest production graph and setting this to p99 + drain margin.
    AP_SYNC_RESULT_TIMEOUT_S: float = 3900.0

    model_config = {"env_prefix": "CORTEX_MEMORY_"}

    @model_validator(mode="after")
    def _set_runtime(self) -> "MemorySettings":
        if not self.RUNTIME:
            self.RUNTIME = _detect_runtime()
        return self

    @property
    def db_path_resolved(self) -> Path:
        return Path(self.DB_PATH).expanduser()

    @property
    def mcp_pool_max_connections(self) -> int:
        """Effective max live MCP child connections in the pool.

        Resolves the ``0 = auto`` sentinel to ``max(2, os.cpu_count())``.
        os.cpu_count() can return None (rare, e.g. unsupported platform);
        treat that as a single core and fall back to the floor of 2.
        source: MCP_POOL_MAX_CONNECTIONS field comment.
        """
        if self.MCP_POOL_MAX_CONNECTIONS > 0:
            return self.MCP_POOL_MAX_CONNECTIONS
        cores = os.cpu_count() or 1
        return max(2, cores)


@lru_cache(maxsize=1)
def get_memory_settings() -> MemorySettings:
    """Singleton memory settings instance."""
    return MemorySettings()


def root_agent_topic() -> str | None:
    """Launch-time capability scope for connection-rooted isolation.

    When ``CORTEX_ROOT_AGENT_TOPIC`` is set in the environment, the server
    FORCES this ``agent_topic`` on every recall/remember and strips the
    ``agent_topic`` argument from the registered tool schemas. This is
    capability-style scoping (cf. supermemory's ``x-sm-project`` header):
    the model cannot target — or accidentally omit — another scope, because
    the parameter is not exposed to it at all.

    Read once at process start (single-process FastMCP stdio server), so a
    plain env read with no caching layer is sufficient. Empty/unset → None,
    meaning no rooting (the ``agent_topic`` parameter behaves as before).
    """
    val = os.environ.get("CORTEX_ROOT_AGENT_TOPIC", "").strip()
    return val or None
