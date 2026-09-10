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

    # source: ADR-0534
    DATABASE_URL: str = "postgresql://127.0.0.1:5432/cortex"
    DB_PATH: str = str(METHODOLOGY_DIR / "memory.db")  # source: ADR-0534
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

    # source: ADR-0534
    SA_DECAY: float = 0.65
    SA_THRESHOLD: float = 0.1
    SA_MAX_DEPTH: int = 3
    SA_MAX_NODES: int = 50

    # ── Write Gate (Predictive Coding) ────────────────────────────────────
    WRITE_GATE_THRESHOLD: float = 0.4
    WRITE_GATE_CONTINUITY_DISCOUNT: float = 0.15
    WRITE_GATE_CONTINUITY_WINDOW: int = 10
    # source: ADR-0534
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

    # source: ADR-0534
    RECENCY_BOOST_MAX: float = 0.15  # Maximum recency bonus
    RECENCY_BOOST_HALFLIFE_DAYS: float = 30.0  # Exponential decay half-life
    RECENCY_BOOST_CUTOFF_DAYS: float = 90.0  # No boost after this age

    # source: ADR-0534
    STRATEGIC_ORDERING_ENABLED: bool = True
    STRATEGIC_TOP_FRACTION: float = 0.3  # Top 30% at start
    STRATEGIC_BOTTOM_FRACTION: float = 0.2  # Bottom 20% at end

    # source: ADR-0534
    SURPRISE_MOMENTUM_ENABLED: bool = True
    SURPRISE_MOMENTUM_ETA: float = 0.7  # momentum decay (EMA)
    SURPRISE_MOMENTUM_DELTA: float = 0.08  # max heat change per recall

    # source: ADR-0534
    ADAPTIVE_DECAY_ENABLED: bool = True
    ADAPTIVE_DECAY_MIN_RATE: float = 0.90
    ADAPTIVE_DECAY_MAX_RATE: float = 0.999

    # source: ADR-0534
    CO_ACTIVATION_ENABLED: bool = True
    CO_ACTIVATION_LEARNING_RATE: float = 0.1
    CO_ACTIVATION_MIN_SCORE: float = 0.3

    # source: ADR-0534
    MAX_RESPONSE_CHARS: int = 75_000

    # ── Embedding ─────────────────────────────────────────────────────────
    EMBEDDING_DIM: int = 384
    EMBEDDING_DEVICE: str = "cpu"  # "cpu" | "auto" | "cuda" | "mps"

    # source: ADR-0534
    A3_LAZY_HEAT: bool = True

    # source: ADR-0534
    POOL_INTERACTIVE_MIN: int = 2
    POOL_INTERACTIVE_MAX: int = 8
    POOL_INTERACTIVE_TIMEOUT_S: float = 5.0

    # source: ADR-0534
    POOL_BATCH_MIN: int = 1
    POOL_BATCH_MAX: int = 2
    POOL_BATCH_TIMEOUT_S: float = 1800.0  # source: ADR-0534

    # source: ADR-0534
    POOL_DISABLED: bool = False

    # source: ADR-0534
    MCP_POOL_MAX_CONNECTIONS: int = 0

    # source: ADR-0534
    AP_ENABLED: bool = True

    # source: ADR-0534

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

        source: ADR-0534"""
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

    source: ADR-0534"""
    val = os.environ.get("CORTEX_ROOT_AGENT_TOPIC", "").strip()
    return val or None
