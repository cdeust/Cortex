"""Memory system configuration — extends JARVIS config with thermodynamic memory settings.

All settings are overridable via JARVIS_MEMORY_ env prefix.
Defaults tuned from production parameters.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

from mcp_server.infrastructure.config import METHODOLOGY_DIR


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

    # ── Storage (PostgreSQL mandatory) ────────────────────────────────────
    DATABASE_URL: str = "postgresql://localhost:5432/cortex"
    DB_PATH: str = str(METHODOLOGY_DIR / "memory.db")  # deprecated, kept for migration
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

    # ── Embedding ─────────────────────────────────────────────────────────
    EMBEDDING_DIM: int = 384

    model_config = {"env_prefix": "JARVIS_MEMORY_"}

    @property
    def db_path_resolved(self) -> Path:
        return Path(self.DB_PATH).expanduser()


@lru_cache(maxsize=1)
def get_memory_settings() -> MemorySettings:
    """Singleton memory settings instance."""
    return MemorySettings()
