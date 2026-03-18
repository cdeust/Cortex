"""Pydantic data models for the memory subsystem.

Extends shared/types.py with memory-specific models. These define the
schema for SQLite storage and handler I/O — the memory system's contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ─── Core Memory Models ──────────────────────────────────────────────────────


class Memory(BaseModel):
    """A single memory unit with thermodynamic properties."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    content: str
    embedding: bytes | None = None
    tags: list[str] = Field(default_factory=list)
    source: str = ""  # "session", "tool", "user", "consolidation"
    domain: str = ""
    directory_context: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: datetime = Field(default_factory=datetime.utcnow)

    # Thermodynamic properties
    heat: float = 1.0
    surprise_score: float = 0.0
    importance: float = 0.5
    emotional_valence: float = 0.0
    confidence: float = 1.0

    # Access tracking (metamemory)
    access_count: int = 0
    useful_count: int = 0

    # Reconsolidation state
    plasticity: float = 1.0
    stability: float = 0.0
    reconsolidation_count: int = 0
    last_reconsolidated: datetime | None = None

    # Store type (CLS dual-store)
    store_type: Literal["episodic", "semantic"] = "episodic"

    # Compression
    compressed: bool = False
    compression_level: int = 0  # 0=full, 1=gist, 2=tag
    original_content: str | None = None

    # Protection
    is_protected: bool = False
    is_stale: bool = False

    # Engram allocation
    slot_index: int | None = None
    excitability: float = 1.0

    # Consolidation cascade (Kandel 2001, Dudai 2012)
    consolidation_stage: str = (
        "labile"  # labile/early_ltp/late_ltp/consolidated/reconsolidating
    )
    hours_in_stage: float = 0.0
    replay_count: int = 0

    # Oscillatory context (Hasselmo 2005, Buzsaki 2015)
    theta_phase_at_encoding: float = 0.0  # Phase of theta cycle when memory was created
    encoding_strength: float = 1.0  # Phase-modulated initial encoding strength

    # Pattern separation (Leutgeb 2007, Yassa & Stark 2011)
    separation_index: float = 0.0  # How much DG orthogonalization was applied [0,1]
    interference_score: float = 0.0  # Current interference pressure from neighbors

    # Schema integration (Tse 2007, Gilboa & Marlatte 2017)
    schema_match_score: float = 0.0  # Match to best schema [0,1]
    schema_id: str | None = None  # Which schema this memory matched

    # Hippocampal dependency (McClelland 1995)
    hippocampal_dependency: float = (
        1.0  # 1.0=fully hippocampal, 0.0=cortically independent
    )


class Entity(BaseModel):
    """A named entity extracted from memories (file, function, decision, etc.)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str
    type: Literal[
        "file",
        "function",
        "variable",
        "dependency",
        "decision",
        "error",
        "solution",
        "domain",
        "pattern",
    ]
    domain: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed: datetime = Field(default_factory=datetime.utcnow)
    heat: float = 1.0
    archived: bool = False


class Relationship(BaseModel):
    """A typed edge between two entities."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    source_entity_id: int
    target_entity_id: int
    relationship_type: (
        str  # co_occurrence, imports, calls, caused_by, resolved_by, etc.
    )
    weight: float = 1.0
    is_causal: bool = False
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_reinforced: datetime = Field(default_factory=datetime.utcnow)

    # Stochastic synaptic transmission (Markram 1998, Abbott & Regehr 2004)
    release_probability: float = 0.5  # p(transmission) per access [0,1]
    facilitation: float = 0.0  # Short-term facilitation accumulator
    depression: float = 0.0  # Short-term depression accumulator


# ─── Prospective Memory ──────────────────────────────────────────────────────


class ProspectiveTrigger(BaseModel):
    """A future-oriented memory trigger that fires on context match."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    content: str
    trigger_condition: str
    trigger_type: Literal[
        "directory_match", "keyword_match", "entity_match", "time_based"
    ]
    target_directory: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    triggered_at: datetime | None = None
    triggered_count: int = 0


# ─── Checkpoint (Hippocampal Replay) ──────────────────────────────────────────


class Checkpoint(BaseModel):
    """Working state snapshot for post-compaction recovery."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    session_id: str = "default"
    directory_context: str = ""
    current_task: str = ""
    files_being_edited: list[str] = Field(default_factory=list)
    key_decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    active_errors: list[str] = Field(default_factory=list)
    custom_context: str = ""
    epoch: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = True


# ─── Archive ──────────────────────────────────────────────────────────────────


class MemoryArchive(BaseModel):
    """Archived version of a memory before reconsolidation/extinction."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    original_memory_id: int
    content: str
    embedding: bytes | None = None
    archived_at: datetime = Field(default_factory=datetime.utcnow)
    mismatch_score: float = 0.0
    archive_reason: str = ""  # "reconsolidation", "compression", "extinction"


# ─── Consolidation Log ───────────────────────────────────────────────────────


class ConsolidationLog(BaseModel):
    """Record of a consolidation run."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    memories_added: int = 0
    memories_updated: int = 0
    memories_archived: int = 0
    duration_ms: int = 0


# ─── Stats ────────────────────────────────────────────────────────────────────


class MemoryStats(BaseModel):
    """Aggregate memory system statistics."""

    model_config = ConfigDict(extra="ignore")

    total_memories: int = 0
    episodic_count: int = 0
    semantic_count: int = 0
    active_count: int = 0
    archived_count: int = 0
    stale_count: int = 0
    protected_count: int = 0
    avg_heat: float = 0.0
    total_entities: int = 0
    total_relationships: int = 0
    active_triggers: int = 0
    last_consolidation: datetime | None = None

    # Consolidation stage distribution
    labile_count: int = 0
    early_ltp_count: int = 0
    late_ltp_count: int = 0
    consolidated_count: int = 0
    reconsolidating_count: int = 0
    avg_interference_score: float = 0.0
    schema_count: int = 0
    distribution_health: float = 0.0


# ─── Recall Result ────────────────────────────────────────────────────────────


class RecallResult(BaseModel):
    """A single memory retrieval result with relevance scoring."""

    model_config = ConfigDict(extra="ignore")

    memory_id: int
    content: str
    score: float = 0.0
    heat: float = 0.0
    domain: str = ""
    tags: list[str] = Field(default_factory=list)
    store_type: str = "episodic"
    created_at: str = ""
    signals: dict[str, float] = Field(default_factory=dict)  # Per-signal scores
