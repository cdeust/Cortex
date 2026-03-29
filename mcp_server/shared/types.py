"""Centralized Pydantic type definitions for the methodology-agent system.

Memory, graph, and interpretability models live here. Profile-related
models are defined in types_profiles.py.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Conversation / Memory Metadata ---


class ConversationMeta(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    slug: str | None = None
    project: str = ""
    cwd: str | None = None
    first_message: str | None = Field(default=None, alias="firstMessage")
    all_text: str | None = Field(default=None, alias="allText")
    keywords: list[str] = Field(default_factory=list)
    started_at: str | None = Field(default=None, alias="startedAt")
    ended_at: str | None = Field(default=None, alias="endedAt")
    message_count: int = Field(default=0, alias="messageCount")
    user_count: int = Field(default=0, alias="userCount")
    assistant_count: int = Field(default=0, alias="assistantCount")
    turn_count: int = Field(default=0, alias="turnCount")
    tools_used: list[str] = Field(default_factory=list, alias="toolsUsed")
    duration: float | None = None
    file_size: int | None = Field(default=None, alias="fileSize")


class MemoryMeta(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    file: str = ""
    path: str = ""
    project: str = ""
    name: str = ""
    description: str = ""
    type: str = ""
    body: str = ""
    modified_at: str = Field(default="", alias="modifiedAt")
    created_at: str | None = Field(default=None, alias="createdAt")


# --- Graph Types ---


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: Literal["domain", "entry-point", "recurring-pattern", "tool-preference"]
    label: str = ""
    domain: str = ""
    confidence: float | None = None
    frequency: int | None = None
    ratio: float | None = None
    color: str = "#999999"
    size: float = 1.0


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    type: Literal["has-entry", "has-pattern", "uses-tool", "bridge"]
    weight: float = 1.0
    label: str | None = None


class GraphData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    blind_spot_regions: list[dict[str, Any]] = Field(
        default_factory=list, alias="blindSpotRegions"
    )


# --- Interpretability Types ---


class TopSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    signal: str
    weight: float


class BehavioralFeature(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    index: int
    label: str = ""
    description: str = ""
    direction: list[float] = Field(default_factory=list)
    top_signals: list[TopSignal] = Field(default_factory=list, alias="topSignals")


class SparseActivation(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    weights: dict[str, float] = Field(default_factory=dict)
    reconstruction_error: float = Field(default=0.0, alias="reconstructionError")


class AttributionNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str = ""
    layer: Literal[
        "input", "extractor", "classifier", "feature", "aggregator", "output"
    ]
    activation: float = 0.0


class AttributionEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    weight: float = 0.0


class AttributionGraph(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nodes: list[AttributionNode] = Field(default_factory=list)
    edges: list[AttributionEdge] = Field(default_factory=list)


class PersonaVector(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    active_reflective: float = Field(default=0.0, alias="activeReflective")
    sensing_intuitive: float = Field(default=0.0, alias="sensingIntuitive")
    sequential_global: float = Field(default=0.0, alias="sequentialGlobal")
    thoroughness: float = 0.0
    autonomy: float = 0.0
    verbosity: float = 0.0
    risk_tolerance: float = Field(default=0.0, alias="riskTolerance")
    focus_scope: float = Field(default=0.0, alias="focusScope")
    iteration_speed: float = Field(default=0.0, alias="iterationSpeed")


class PersistentFeature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    persistence: float = 0.0
    consistency: float = 0.0
    domains: list[str] = Field(default_factory=list)


class FeatureDictionary(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    k: int = Field(alias="K")
    d: int = Field(alias="D")
    sparsity: int = 0
    signal_names: list[str] = Field(default_factory=list, alias="signalNames")
    features: list[BehavioralFeature] = Field(default_factory=list)
    learned_from_sessions: int = Field(default=0, alias="learnedFromSessions")
