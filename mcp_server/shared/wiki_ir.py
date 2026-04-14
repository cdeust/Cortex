"""Wiki pipeline Intermediate Representations (Phase 1 of redesign).

Each IR is a named, inspectable boundary between pipeline phases:

    transcript → [ClaimEvent] → [Concept] → [DraftPage] → [ApprovedPage] → rendered

These are Pydantic models (v2) so they round-trip JSON for DB storage
(JSONB columns) and MCP tool payloads, and validate at the boundary.

Pure data — no I/O. Imports: shared + stdlib only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── Phase output: transcript → ClaimEvent ─────────────────────────────
# Extracted from a raw session / memory. Atomic, timestamped, citable.

ClaimType = Literal[
    "assertion",
    "decision",
    "observation",
    "question",
    "method",
    "result",
    "limitation",
    "reference",
]


class ClaimEvent(BaseModel):
    """Atomic extracted assertion from a transcript or memory.

    The "laboratory notebook" layer — Hopper's nanosecond wire.
    One claim = one falsifiable/citable unit. If it needs an "and",
    it should be split into two ClaimEvents.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int | None = None
    memory_id: int | None = None
    session_id: str = ""
    text: str = Field(..., min_length=1, max_length=2000)
    claim_type: ClaimType = "assertion"
    entity_ids: list[int] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    supersedes: int | None = None
    extracted_at: datetime | None = None


class EvidenceRef(BaseModel):
    """A pointer to supporting evidence for a claim.

    Kinds:
      - file: a source file in the repo (path + optional line range)
      - commit: a git commit SHA
      - paper: arxiv / DOI / URL
      - memory: another memory this claim derives from
      - claim: another claim that supports this one
      - benchmark: a named benchmark result
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file", "commit", "paper", "memory", "claim", "benchmark", "url"]
    target: str
    context: str | None = None


# ── Phase output: ClaimEvents → Concept ───────────────────────────────
# Emergent candidate knowledge node. Strauss axial coding.
# Sits between memories and pages.

ConceptStatus = Literal[
    "candidate",
    "saturating",
    "promoted",
    "merged",
    "split",
    "abandoned",
]


class AxialSlots(BaseModel):
    """The four axial-coding slots per Strauss & Corbin.

    A concept graduates from candidate → saturating when at least
    three of the four slots are non-empty.
    """

    model_config = ConfigDict(extra="forbid")

    conditions: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)


class Concept(BaseModel):
    """Candidate concept emerging from entity co-occurrence + embedding density.

    Promotion to page requires:
      - ≥ M grounding memories (default M = 3)
      - ≥ 3 of 4 axial slots populated
      - saturation_streak ≥ N consecutive memories with no new properties
        (default N = 5)
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int | None = None
    label: str = Field(..., min_length=1, max_length=200)
    status: ConceptStatus = "candidate"
    entity_ids: list[int] = Field(default_factory=list)
    grounding_memory_ids: list[int] = Field(default_factory=list)
    grounding_claim_ids: list[int] = Field(default_factory=list)
    properties: dict[str, list[str]] = Field(default_factory=dict)
    axial_slots: AxialSlots = Field(default_factory=AxialSlots)
    saturation_rate: float = 1.0
    saturation_streak: int = 0
    first_seen_at: datetime | None = None
    last_property_at: datetime | None = None
    promoted_page_id: int | None = None
    merged_into_id: int | None = None
    split_into_ids: list[int] = Field(default_factory=list)


# ── Phase output: Concept + Claims → DraftPage ────────────────────────
# Pre-curation synthesis. Inspectable before approval.

DraftStatus = Literal["pending", "approved", "rejected", "published"]


class Section(BaseModel):
    """A named section of a draft/approved page."""

    model_config = ConfigDict(extra="forbid")

    heading: str
    body: str
    claim_ids: list[int] = Field(default_factory=list)


class Provenance(BaseModel):
    """Where the draft came from — necessary for zetetic audit."""

    model_config = ConfigDict(extra="forbid")

    source_type: Literal["concept", "memory", "user", "claim-set"] = "concept"
    source_ids: list[int] = Field(default_factory=list)
    synthesis_model: str | None = None
    synthesis_prompt_hash: str | None = None
    generated_at: datetime | None = None


class DraftPage(BaseModel):
    """Synthesised page awaiting curation (approval/rejection).

    Produced by the synthesise phase from a Concept + its ClaimEvents.
    Human or rule-driven gate decides promotion to ApprovedPage.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int | None = None
    concept_id: int | None = None
    memory_id: int | None = None
    title: str = Field(..., min_length=1, max_length=300)
    kind: str
    lead: str = Field("", max_length=500)
    sections: list[Section] = Field(default_factory=list)
    frontmatter: dict = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    status: DraftStatus = "pending"


# ── Phase output: DraftPage → ApprovedPage ────────────────────────────
# The authored, published wiki page. Mirrored to .md file (source of truth)
# AND to wiki.pages row (queryable facet index).

PageStatus = Literal["seedling", "budding", "evergreen"]
LifecycleState = Literal["active", "area", "archived", "evergreen"]


class ApprovedPage(BaseModel):
    """Published wiki page with thermodynamic state + facet metadata."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int | None = None
    memory_id: int | None = None
    concept_id: int | None = None
    rel_path: str
    slug: str
    kind: str
    title: str
    domain: str = ""
    domains: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    audience: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    status: PageStatus = "seedling"
    lifecycle_state: LifecycleState = "active"
    supersedes: str | None = None
    superseded_by: str | None = None
    verified: str | None = None
    lead: str
    sections: list[Section] = Field(default_factory=list)
    body_hash: str = ""
    # thermodynamic survival state
    heat: float = Field(1.0, ge=0.0, le=1.0)
    access_count: int = 0
    citation_count: int = 0
    backlink_count: int = 0
    is_stale: bool = False
    planted: datetime | None = None
    tended: datetime | None = None


# ── Curation memo (Strauss memoing) ────────────────────────────────────
# Every pipeline decision writes a memo. Audit trail for the
# grounded-theory process.

MemoSubject = Literal["concept", "draft", "page", "claim"]


class CurationMemo(BaseModel):
    """The grounded-theory memoing layer.

    Captures *why* a decision was made: the inputs considered, the
    alternatives rejected, and the confidence. Without this, grounded
    theory is not grounded.
    """

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    subject_type: MemoSubject
    subject_id: int
    decision: str
    rationale: str = ""
    alternatives: list[dict] = Field(default_factory=list)
    inputs: dict = Field(default_factory=dict)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    author: str = "system"
    created_at: datetime | None = None


# Forward reference resolution for ClaimEvent.evidence_refs
ClaimEvent.model_rebuild()
