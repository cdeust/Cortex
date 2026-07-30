"""Typed shapes for the explore_features interpretability lenses.

Types the internal core-layer boundary between mcp_server/core/{persona_vector,
attribution_tracer, behavioral_crosscoder, sparse_dictionary}.py and their
consumers (mcp_server/handlers/explore_features.py,
mcp_server/core/profile_assembler.py). Prior to this module those functions
returned dict[str, Any] — a §3.2 coding-standards violation (untyped dict
across a layer boundary).

Field names mirror the JSON keys these modules already produce (camelCase,
matching the JS-era MCP/profiles.json contract). This is a typing-only
refactor: it does not change what is computed, only what carries the result.

Two data-provenance families, two ``extra`` policies:
  - FeatureDictionary / Feature / TopSignal / PersistentFeature round-trip
    through profiles.json (written by profile_assembler.py, re-read by
    explore_features.py via load_profiles()). They use extra="ignore" —
    the same tolerance types_profiles.py uses for JS-authored data.
  - EncodedSession / PersonaDrift / AttributionNode / AttributionEdge /
    AttributionGraph are computed fresh in-process every call and never
    persisted. They use extra="forbid" — the stricter policy wiki_ir.py
    uses for pure-internal pipeline types.

Feature.direction is Optional: the live sparse_dictionary.py output always
includes it, but profile_assembler._build_feature_dictionary() strips it
before persisting to profiles.json (disk-loaded features never carry it).
This models the real observed union of shapes, not an approximation.
"""

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

    activation is always numeric. 3 of the 6 classifier nodes
    (problemDecomposition, explorationStyle, verificationBehavior) classify
    a *categorical* CognitiveStyle value (see types_profiles.CognitiveStyle,
    e.g. "top-down"/"bottom-up") that has no legitimate scalar magnitude --
    fabricating a number for it would be a silent, unsourced cast. Those
    three nodes carry activation=0.0 (no measured magnitude) and expose the
    classification separately via categoricalValue. The other three
    classifier nodes and all non-classifier nodes leave categoricalValue
    unset and carry a real float in activation.
    """

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
