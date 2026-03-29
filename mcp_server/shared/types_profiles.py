"""Profile-related Pydantic models for the methodology-agent system.

These models define the cognitive profiling types: patterns, styles,
bridges, blind spots, detection, and domain profiles. They must be
compatible with the existing profiles.json format written by the JS server.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- Pattern Types ---


class EntryPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pattern: str
    frequency: int = 0
    confidence: float = 0.0
    example_messages: list[str] = Field(default_factory=list, alias="exampleMessages")


class RecurringPattern(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pattern: str
    ngram_signature: list[str] = Field(default_factory=list, alias="ngramSignature")
    frequency: int = 0
    sessions_observed: int = Field(default=0, alias="sessionsObserved")
    confidence: float = 0.0


class ToolPreference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ratio: float = 0.0
    avg_per_session: float = Field(default=0.0, alias="avgPerSession")


class SessionShape(BaseModel):
    model_config = ConfigDict(extra="ignore")

    avg_duration: float = Field(default=0.0, alias="avgDuration")
    avg_turns: float = Field(default=0.0, alias="avgTurns")
    avg_messages: float = Field(default=0.0, alias="avgMessages")
    burst_ratio: float = Field(default=0.0, alias="burstRatio")
    exploration_ratio: float = Field(default=0.0, alias="explorationRatio")
    dominant_mode: Literal["burst", "exploration", "mixed"] = Field(
        default="mixed", alias="dominantMode"
    )


# --- Style Types ---


class CognitiveStyle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_reflective: float = Field(default=0.0, alias="activeReflective")
    sensing_intuitive: float = Field(default=0.0, alias="sensingIntuitive")
    sequential_global: float = Field(default=0.0, alias="sequentialGlobal")
    problem_decomposition: Literal["top-down", "bottom-up"] = Field(
        default="top-down", alias="problemDecomposition"
    )
    exploration_style: Literal["depth-first", "breadth-first"] = Field(
        default="depth-first", alias="explorationStyle"
    )
    verification_behavior: Literal["test-first", "test-after", "no-test"] = Field(
        default="no-test", alias="verificationBehavior"
    )


class GlobalStyle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    active_reflective: float = Field(default=0.0, alias="activeReflective")
    sensing_intuitive: float = Field(default=0.0, alias="sensingIntuitive")
    sequential_global: float = Field(default=0.0, alias="sequentialGlobal")
    confidence: float = 0.0
    session_count: int = Field(default=0, alias="sessionCount")


# --- Bridge & Blind Spot Types ---


class Bridge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    to_domain: str = Field(alias="toDomain")
    pattern: str = ""
    weight: float = 0.0
    examples: list[dict[str, Any]] = Field(default_factory=list)
    edge_count: int = Field(default=0, alias="edgeCount")


class BlindSpot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["category", "tool", "pattern"]
    value: str
    severity: Literal["high", "medium", "low"] = "medium"
    description: str = ""
    suggestion: str = ""


# --- Detection Types ---


class DetectionContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cwd: str | None = None
    project: str | None = None
    first_message: str | None = None


class AlternativeDomain(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    confidence: float = 0.0


class DetectionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cold_start: bool = Field(default=False, alias="coldStart")
    domain: str | None = None
    confidence: float = 0.0
    is_new: bool = Field(default=False, alias="isNew")
    alternative_domains: list[AlternativeDomain] = Field(
        default_factory=list, alias="alternativeDomains"
    )
    context: str | None = None


# --- Profile Types ---


class DomainProfile(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    label: str = ""
    projects: list[str] = Field(default_factory=list)
    categories: dict[str, float] = Field(default_factory=dict)
    top_keywords: list[str] = Field(default_factory=list, alias="topKeywords")
    entry_points: list[EntryPoint] = Field(default_factory=list, alias="entryPoints")
    recurring_patterns: list[RecurringPattern] = Field(
        default_factory=list, alias="recurringPatterns"
    )
    tool_preferences: dict[str, ToolPreference] = Field(
        default_factory=dict, alias="toolPreferences"
    )
    session_shape: SessionShape | None = Field(default=None, alias="sessionShape")
    connection_bridges: list[Bridge] = Field(
        default_factory=list, alias="connectionBridges"
    )
    blind_spots: list[BlindSpot] = Field(default_factory=list, alias="blindSpots")
    metacognitive: CognitiveStyle | None = None
    confidence: float = 0.0
    session_count: int = Field(default=0, alias="sessionCount")
    last_updated: str | None = Field(default=None, alias="lastUpdated")
    first_seen: str | None = Field(default=None, alias="firstSeen")


class ProfilesV2(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    version: int = 2
    updated_at: str | None = Field(default=None, alias="updatedAt")
    global_style: GlobalStyle | None = Field(default=None, alias="globalStyle")
    domains: dict[str, DomainProfile] = Field(default_factory=dict)


# --- Session Log Types ---


class SessionLogEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    domain: str = ""
    timestamp: str = ""
    project: str | None = None
    cwd: str | None = None
    duration: float | None = None
    turn_count: int = Field(default=0, alias="turnCount")
    tools_used: list[str] = Field(default_factory=list, alias="toolsUsed")
    category: str = ""
    entry_keywords: list[str] = Field(default_factory=list, alias="entryKeywords")


class SessionLog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sessions: list[SessionLogEntry] = Field(default_factory=list)
