"""Phase 3 — Concept emergence (Strauss grounded-theory mechanics).

Inputs:
    claim_events with entity_ids and claim_type
    existing wiki.concepts state (for incremental update)

Outputs:
    EmergencePlans the handler persists into wiki.concepts:
      - new candidate concepts (clusters)
      - axial_slot updates
      - saturation_streak / status transitions
      - merge / split / promote candidates

Algorithm (deterministic, server-side, no LLM):

  1. Group claims by entity_id → per-entity claim sets
  2. For each entity with ≥ MIN_CLAIMS_PER_CONCEPT claims, form a
     candidate concept with that entity as its center
  3. Merge candidates whose claim_id sets overlap > MERGE_JACCARD
  4. For each (existing or new) concept, compute:
     - axial_slots: distribute claim texts by claim_type into
       Strauss's four buckets (conditions, context, strategies,
       consequences)
     - new_properties_this_pass: claim types/phrases not seen before
     - saturation_rate: rolling rate of new_properties / new_memories
     - saturation_streak: consecutive memories that added nothing
  5. Promote a concept to 'saturating' when saturation_streak ≥ 3
  6. Promote to 'promoted' (ready for synthesis) when:
     - len(grounding_memory_ids) ≥ MIN_GROUNDING_MEMORIES
     - axial_slots: ≥ 3 of 4 non-empty
     - saturation_streak ≥ 5

Pure logic, no I/O. The handler wires this against pg_store_wiki.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal


# ── Tunable thresholds ────────────────────────────────────────────────

MIN_CLAIMS_PER_CONCEPT = 3
MERGE_JACCARD = 0.5
SATURATION_PROMOTE_STREAK = 3
PROMOTION_PROMOTE_STREAK = 5
MIN_GROUNDING_MEMORIES = 3
MIN_AXIAL_SLOTS_FILLED = 3
ABANDON_AFTER_DAYS = 60  # candidates that never grow

ConceptStatus = Literal[
    "candidate", "saturating", "promoted", "merged", "split", "abandoned"
]


# ── Axial coding ──────────────────────────────────────────────────────
#
# Strauss & Corbin's coding paradigm — distribute claims into four
# slots that together describe the concept structurally:
#
#   conditions   — what gives rise to the phenomenon
#   context      — the conditions in which strategies are taken
#   strategies   — actions/methods used
#   consequences — what results
#
# Mapped from claim_type because the extractor already typed each claim.

_AXIAL_FROM_CLAIM_TYPE: dict[str, str] = {
    "observation": "conditions",
    "limitation": "conditions",
    "decision": "strategies",
    "method": "strategies",
    "result": "consequences",
    "reference": "context",
    "question": "context",
    "assertion": "context",
}


# ── Plan dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ConceptPlan:
    """Per-concept update plan (insert or update)."""

    concept_id: int | None  # None → new candidate
    label: str
    entity_ids: list[int]
    grounding_memory_ids: list[int]
    grounding_claim_ids: list[int]
    properties: dict[str, list[str]]
    axial_slots: dict[str, list[str]]
    saturation_rate: float
    saturation_streak: int
    status: ConceptStatus


@dataclass(frozen=True)
class EmergenceStats:
    candidate_concepts: int
    promoted: int
    saturating: int
    abandoned: int
    claims_grouped: int
    new_concepts: int
    updated_concepts: int


# ── Helpers ───────────────────────────────────────────────────────────


def _entity_label(claim_texts: list[str], entity_id: int) -> str:
    """Pick a stable label for the candidate concept.

    Heuristic: take the most-common 2-3 word noun-phrase fragment that
    appears across the claim texts. Falls back to a generic
    'concept-<entity_id>' if no good label.
    """
    if not claim_texts:
        return f"concept-{entity_id}"
    # Extract candidate terms: capitalised tokens or snake_case identifiers
    counts: Counter[str] = Counter()
    for t in claim_texts:
        for m in re.finditer(r"\b([A-Z][a-zA-Z]+|[a-z]+_[a-z_]+)\b", t):
            tok = m.group(1)
            if 3 <= len(tok) <= 40:
                counts[tok] += 1
    if not counts:
        return f"concept-{entity_id}"
    return counts.most_common(1)[0][0]


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _axial_distribution(claims: list[dict]) -> dict[str, list[str]]:
    """Distribute claim texts into the four axial slots."""
    slots: dict[str, list[str]] = {
        "conditions": [],
        "context": [],
        "strategies": [],
        "consequences": [],
    }
    for c in claims:
        slot = _AXIAL_FROM_CLAIM_TYPE.get(c.get("claim_type", ""), "context")
        text = (c.get("text") or "").strip()
        if text and text not in slots[slot]:
            slots[slot].append(text[:300])
    return slots


def _properties_from_claims(claims: list[dict]) -> dict[str, list[str]]:
    """Extract a property set: claim_type → list of distinct text fingerprints."""
    props: dict[str, list[str]] = {}
    for c in claims:
        ct = c.get("claim_type", "assertion")
        # Fingerprint = first 80 chars (collapses near-duplicates)
        fp = (c.get("text") or "").strip()[:80]
        if not fp:
            continue
        props.setdefault(ct, [])
        if fp not in props[ct]:
            props[ct].append(fp)
    return props


def _count_axial_slots_filled(slots: dict[str, list[str]]) -> int:
    return sum(1 for v in slots.values() if v)


# ── Clustering ────────────────────────────────────────────────────────


@dataclass
class _Cluster:
    center_entity: int
    entity_ids: set[int] = field(default_factory=set)
    claim_ids: set[int] = field(default_factory=set)
    memory_ids: set[int] = field(default_factory=set)


def _cluster_by_entity(
    claims: list[dict],
    min_claims: int = MIN_CLAIMS_PER_CONCEPT,
) -> list[_Cluster]:
    """Form one cluster per entity that has ≥ min_claims claims, then
    merge clusters with high claim-set overlap.
    """
    by_entity: dict[int, _Cluster] = {}
    for c in claims:
        cid = c.get("id")
        mid = c.get("memory_id")
        for eid in c.get("entity_ids") or []:
            cluster = by_entity.setdefault(eid, _Cluster(center_entity=eid))
            cluster.entity_ids.add(eid)
            if cid:
                cluster.claim_ids.add(cid)
            if mid:
                cluster.memory_ids.add(mid)

    seeds = [c for c in by_entity.values() if len(c.claim_ids) >= min_claims]

    # Merge by Jaccard on claim_ids (transitive closure via simple loop)
    merged: list[_Cluster] = []
    for seed in sorted(seeds, key=lambda c: -len(c.claim_ids)):
        absorbed = False
        for existing in merged:
            if _jaccard(seed.claim_ids, existing.claim_ids) >= MERGE_JACCARD:
                existing.entity_ids |= seed.entity_ids
                existing.claim_ids |= seed.claim_ids
                existing.memory_ids |= seed.memory_ids
                absorbed = True
                break
        if not absorbed:
            merged.append(seed)
    return merged


# ── Saturation detection ──────────────────────────────────────────────


def _saturation_update(
    existing_props: dict[str, list[str]],
    existing_memory_ids: set[int],
    existing_streak: int,
    new_props: dict[str, list[str]],
    new_memory_ids: set[int],
) -> tuple[float, int]:
    """Compute (saturation_rate, saturation_streak) given a delta.

    new_property_count = number of (claim_type, fingerprint) pairs in
    new_props that were NOT in existing_props.
    new_memory_count = |new_memory_ids - existing_memory_ids|.
    rate = new_property_count / max(1, new_memory_count).

    streak: if rate == 0 and there ARE new memories → existing_streak + 1.
            else if rate > 0 → reset to 0.
            else → unchanged.
    """
    delta_memories = new_memory_ids - existing_memory_ids
    new_property_count = 0
    for ct, fps in new_props.items():
        existing_set = set(existing_props.get(ct, []))
        for fp in fps:
            if fp not in existing_set:
                new_property_count += 1
    n_delta_mems = len(delta_memories)
    if n_delta_mems == 0:
        return (0.0, existing_streak)
    rate = new_property_count / n_delta_mems
    if rate == 0:
        return (0.0, existing_streak + 1)
    return (rate, 0)


def _decide_status(
    *,
    grounding_memory_count: int,
    axial_slots_filled: int,
    saturation_streak: int,
    current_status: ConceptStatus,
) -> ConceptStatus:
    """Apply transition rules. Never moves backwards from promoted."""
    if current_status in ("merged", "split", "abandoned"):
        return current_status
    if current_status == "promoted":
        return "promoted"
    if (
        grounding_memory_count >= MIN_GROUNDING_MEMORIES
        and axial_slots_filled >= MIN_AXIAL_SLOTS_FILLED
        and saturation_streak >= PROMOTION_PROMOTE_STREAK
    ):
        return "promoted"
    if saturation_streak >= SATURATION_PROMOTE_STREAK:
        return "saturating"
    return "candidate"


# ── Public entry point ────────────────────────────────────────────────


def emerge(
    *,
    claims: list[dict],
    existing_concepts_by_entities: dict[int, dict],
) -> tuple[list[ConceptPlan], EmergenceStats]:
    """Run a single emergence pass.

    Inputs:
      claims: list of claim dicts (id, memory_id, text, claim_type,
              entity_ids). Should be the resolved set (entity_ids
              populated by Phase 2.2).
      existing_concepts_by_entities: dict mapping a frozenset of
              entity_ids → existing concept row (id, properties,
              grounding_memory_ids, saturation_streak, status, label).
              Used to do incremental update rather than re-cluster
              from scratch every call.

    Returns (plans, stats). Each ConceptPlan is either:
      - a new candidate (concept_id=None) → handler INSERTs
      - an update to an existing concept (concept_id set) → handler
        UPSERTs by id

    Never raises on bad input.
    """
    if not claims:
        empty_stats = EmergenceStats(0, 0, 0, 0, 0, 0, 0)
        return [], empty_stats

    clusters = _cluster_by_entity(claims)
    plans: list[ConceptPlan] = []
    promoted = 0
    saturating = 0
    abandoned = 0
    new_concepts = 0
    updated_concepts = 0
    claims_grouped = 0

    # Index claims by id for fast lookup
    claims_by_id: dict[int, dict] = {c["id"]: c for c in claims if c.get("id")}

    for cluster in clusters:
        cluster_claims = [
            claims_by_id[cid] for cid in cluster.claim_ids if cid in claims_by_id
        ]
        if not cluster_claims:
            continue
        claims_grouped += len(cluster_claims)

        # Match an existing concept by entity-overlap (frozenset key)
        existing = None
        for ent_key, ec in existing_concepts_by_entities.items():
            ent_set = (
                set(ent_key)
                if isinstance(ent_key, (list, tuple, frozenset))
                else {ent_key}
            )
            if cluster.entity_ids & ent_set:
                # Take the largest-overlap match
                if existing is None or len(cluster.entity_ids & ent_set) > len(
                    cluster.entity_ids & set(existing.get("entity_ids") or [])
                ):
                    existing = ec

        # Compute new state
        new_props = _properties_from_claims(cluster_claims)
        new_axial = _axial_distribution(cluster_claims)

        if existing:
            existing_props = existing.get("properties") or {}
            existing_memory_ids = set(existing.get("grounding_memory_ids") or [])
            existing_streak = int(existing.get("saturation_streak") or 0)
            current_status: ConceptStatus = existing.get("status") or "candidate"
            rate, streak = _saturation_update(
                existing_props,
                existing_memory_ids,
                existing_streak,
                new_props,
                cluster.memory_ids,
            )
            # Merge property sets
            merged_props = {k: list(v) for k, v in existing_props.items()}
            for k, vs in new_props.items():
                merged_props.setdefault(k, [])
                for v in vs:
                    if v not in merged_props[k]:
                        merged_props[k].append(v)
            merged_axial = {
                k: list(v) for k, v in (existing.get("axial_slots") or {}).items()
            }
            for k, vs in new_axial.items():
                merged_axial.setdefault(k, [])
                for v in vs:
                    if v not in merged_axial[k]:
                        merged_axial[k].append(v)
            merged_memory_ids = sorted(existing_memory_ids | cluster.memory_ids)
            merged_claim_ids = sorted(
                set(existing.get("grounding_claim_ids") or []) | cluster.claim_ids
            )
            merged_entity_ids = sorted(
                set(existing.get("entity_ids") or []) | cluster.entity_ids
            )
            new_status = _decide_status(
                grounding_memory_count=len(merged_memory_ids),
                axial_slots_filled=_count_axial_slots_filled(merged_axial),
                saturation_streak=streak,
                current_status=current_status,
            )
            plans.append(
                ConceptPlan(
                    concept_id=existing.get("id"),
                    label=existing.get("label")
                    or _entity_label(
                        [c.get("text", "") for c in cluster_claims],
                        cluster.center_entity,
                    ),
                    entity_ids=merged_entity_ids,
                    grounding_memory_ids=merged_memory_ids,
                    grounding_claim_ids=merged_claim_ids,
                    properties=merged_props,
                    axial_slots=merged_axial,
                    saturation_rate=rate,
                    saturation_streak=streak,
                    status=new_status,
                )
            )
            updated_concepts += 1
        else:
            # New candidate
            label = _entity_label(
                [c.get("text", "") for c in cluster_claims],
                cluster.center_entity,
            )
            status = _decide_status(
                grounding_memory_count=len(cluster.memory_ids),
                axial_slots_filled=_count_axial_slots_filled(new_axial),
                saturation_streak=0,
                current_status="candidate",
            )
            plans.append(
                ConceptPlan(
                    concept_id=None,
                    label=label,
                    entity_ids=sorted(cluster.entity_ids),
                    grounding_memory_ids=sorted(cluster.memory_ids),
                    grounding_claim_ids=sorted(cluster.claim_ids),
                    properties=new_props,
                    axial_slots=new_axial,
                    saturation_rate=1.0,
                    saturation_streak=0,
                    status=status,
                )
            )
            new_concepts += 1

    for p in plans:
        if p.status == "promoted":
            promoted += 1
        elif p.status == "saturating":
            saturating += 1
        elif p.status == "abandoned":
            abandoned += 1

    stats = EmergenceStats(
        candidate_concepts=len(plans),
        promoted=promoted,
        saturating=saturating,
        abandoned=abandoned,
        claims_grouped=claims_grouped,
        new_concepts=new_concepts,
        updated_concepts=updated_concepts,
    )
    return plans, stats
