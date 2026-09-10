"""Typed shapes for the explore_features interpretability lenses.

source: ADR-0673"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TopSignal(BaseModel):
    """One (signal, weight) contribution to a feature's direction."""

    model_config = ConfigDict(extra="ignore")

    signal: str
    weight: float


class Feature(BaseModel):
    """A single behavioral-feature atom (seed or learned)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    index: int
    label: str
    description: str
    top_signals: list[TopSignal] = Field(alias="topSignals")
    direction: list[float] | None = None


class FeatureDictionary(BaseModel):
    """Sparse-dictionary of behavioral feature atoms (K atoms, D=27 dims)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    K: int
    D: int
    sparsity: int
    signal_names: list[str] = Field(alias="signalNames")
    features: list[Feature]
    learned_from_sessions: int = Field(alias="learnedFromSessions")


class EncodedSession(BaseModel):
    """A single conversation's sparse encoding against a FeatureDictionary."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    weights: dict[str, float]
    reconstruction_error: float = Field(alias="reconstructionError")


class PersonaDrift(BaseModel):
    """Magnitude + direction + interpretation of persona change over time."""

    model_config = ConfigDict(extra="forbid")

    magnitude: float
    direction: dict[str, float]
    interpretation: str


class AttributionNode(BaseModel):
    """One node in the pipeline attribution graph.

    source: ADR-0673"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    label: str
    layer: str
    activation: float
    categorical_value: str | None = Field(default=None, alias="categoricalValue")


class AttributionEdge(BaseModel):
    """One perturbation-weighted edge in the pipeline attribution graph."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    weight: float


class AttributionGraph(BaseModel):
    """Full pipeline attribution graph (nodes + edges)."""

    model_config = ConfigDict(extra="forbid")

    nodes: list[AttributionNode]
    edges: list[AttributionEdge]


class PersistentFeature(BaseModel):
    """A behavioral feature persistently active across >=50% of domains."""

    model_config = ConfigDict(extra="ignore")

    label: str
    persistence: float
    consistency: float
    domains: list[str]
