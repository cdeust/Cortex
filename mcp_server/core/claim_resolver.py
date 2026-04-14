"""Phase 2.2 — Claim resolution.

Three responsibilities:

  1. Entity linking — each ClaimEvent inherits its source memory's
     entity_ids (the existing memory_entities join table is the
     authority). Also harvests inline entity name mentions from claim
     text against the entities catalogue.

  2. Supersedes resolution — when a claim's text contains
     "supersedes / replaces / deprecated by", find the most likely
     prior claim it overrides (same entities + earlier in time + same
     claim_type when sensible). Writes claim_events.supersedes.

  3. Conflict detection — claims about the same entities with
     opposing types (decision vs limitation about the same target) are
     surfaced as candidates. Writes a memo per detected pair so the
     curation phase can act on them.

Pure logic — no I/O. The handler wires this against pg_store_wiki.

Design constraint (DBA): the resolver must not JOIN into the memories
hot path. All inputs are pre-fetched by the handler; the resolver
returns plans (entity-id lists, supersedes pairs, conflict pairs) that
the handler persists in idempotent batches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── Resolver outputs ──────────────────────────────────────────────────


@dataclass(frozen=True)
class EntityLinkPlan:
    """Per-claim entity assignment plan."""

    claim_id: int
    entity_ids: list[int]


@dataclass(frozen=True)
class SupersedesPlan:
    """One claim_event.supersedes update."""

    new_claim_id: int
    superseded_claim_id: int
    rationale: str


@dataclass(frozen=True)
class ConflictPlan:
    """A pair of claims that appear to disagree.

    Captured as a memo via ``insert_memo(subject_type='claim', ...)``
    rather than altering either claim — disagreement is data, not a
    correction.
    """

    claim_a_id: int
    claim_b_id: int
    overlap_entities: list[int]
    reason: str


@dataclass(frozen=True)
class ResolveStats:
    claims_processed: int
    entity_links_planned: int
    supersedes_planned: int
    conflicts_planned: int


# ── Entity linking ────────────────────────────────────────────────────


def plan_entity_links(
    claims: list[dict],
    entities_by_memory: dict[int, list[int]],
    entity_name_to_id: dict[str, int] | None = None,
) -> list[EntityLinkPlan]:
    """For each claim, gather entity ids.

    Sources:
      - memory_entities for claim.memory_id (inherited from source)
      - case-insensitive name match on entities catalogue (inline mentions)

    Returns one plan per claim with a deduplicated, sorted entity_id list.
    """
    plans: list[EntityLinkPlan] = []
    name_map = {k.lower(): v for k, v in (entity_name_to_id or {}).items()}
    for c in claims:
        ids = set(entities_by_memory.get(c.get("memory_id"), []))
        if name_map:
            text = (c.get("text") or "").lower()
            # Word-bounded substring — cheap pre-filter, no false positives
            # on partial words. Misses fuzzy matches; that's a Phase 3 problem.
            for name, eid in name_map.items():
                if len(name) < 3:
                    continue
                if re.search(rf"\b{re.escape(name)}\b", text):
                    ids.add(eid)
        plans.append(
            EntityLinkPlan(
                claim_id=c["id"],
                entity_ids=sorted(ids),
            )
        )
    return plans


# ── Supersedes detection ──────────────────────────────────────────────

_SUPERSEDES_PATTERN = re.compile(
    r"\b(supersed(?:es|ed by)|replaces?|replaced by|deprecated by"
    r"|in (?:favour|favor) of|switched (?:to|from)|migrated (?:to|from))\b",
    re.IGNORECASE,
)


def _claim_supersedes_signal(text: str) -> bool:
    return bool(_SUPERSEDES_PATTERN.search(text or ""))


def plan_supersedes(
    claims: list[dict],
    prior_claims_by_entity: dict[int, list[dict]],
) -> list[SupersedesPlan]:
    """Find supersession edges.

    A claim is a supersedes-candidate when its text matches the
    supersedes pattern. We look for prior claims that:
      - share at least one entity_id with the new claim
      - have an earlier extracted_at timestamp
      - have a compatible claim_type (decision supersedes decision,
        method supersedes method; we don't supersede limitations)

    Picks the most-recently-superseded matching prior claim if any.
    Returns one plan per superseder; never raises.
    """
    plans: list[SupersedesPlan] = []
    for c in claims:
        if not _claim_supersedes_signal(c.get("text", "")):
            continue
        if c.get("supersedes"):
            # Already linked; do not overwrite
            continue
        target_types = {
            "decision": {"decision"},
            "method": {"method", "decision"},
            "convention": {"convention", "decision"},
        }.get(c.get("claim_type", ""), set())
        if not target_types:
            continue

        c_entities = set(c.get("entity_ids") or [])
        if not c_entities:
            continue
        c_extracted = c.get("extracted_at")

        # Gather candidate priors that share at least one entity
        candidates: list[dict] = []
        for eid in c_entities:
            for prior in prior_claims_by_entity.get(eid, []):
                if prior.get("id") == c.get("id"):
                    continue
                if prior.get("claim_type") not in target_types:
                    continue
                if c_extracted and prior.get("extracted_at"):
                    if prior["extracted_at"] >= c_extracted:
                        continue
                candidates.append(prior)

        if not candidates:
            continue

        # Pick the latest prior — most likely to be the one being replaced
        best = max(candidates, key=lambda p: p.get("extracted_at") or 0)
        plans.append(
            SupersedesPlan(
                new_claim_id=c["id"],
                superseded_claim_id=best["id"],
                rationale=(
                    f"Supersedes pattern in claim {c['id']} "
                    f"(type={c.get('claim_type')}); prior claim "
                    f"{best['id']} shares entities and predates."
                ),
            )
        )
    return plans


# ── Conflict detection ────────────────────────────────────────────────

# Pairs of claim_types that disagree when about the same entities.
_CONFLICT_PAIRS: dict[tuple[str, str], str] = {
    ("decision", "limitation"): "decision contradicted by reported limitation",
    ("decision", "decision"): "two decisions about the same entities",
    ("method", "limitation"): "method paired with reported limitation",
    ("convention", "limitation"): "convention contradicted by limitation",
}


def _conflict_reason(type_a: str, type_b: str) -> str | None:
    """Return reason text if (type_a, type_b) is a conflicting pair."""
    if (type_a, type_b) in _CONFLICT_PAIRS:
        return _CONFLICT_PAIRS[(type_a, type_b)]
    if (type_b, type_a) in _CONFLICT_PAIRS:
        return _CONFLICT_PAIRS[(type_b, type_a)]
    return None


def plan_conflicts(
    claims: list[dict],
    prior_claims_by_entity: dict[int, list[dict]],
    min_entity_overlap: int = 1,
) -> list[ConflictPlan]:
    """Surface candidate conflicting claim pairs.

    Pair (A, B) is a conflict candidate when:
      - claim_types match _CONFLICT_PAIRS
      - they share ≥ min_entity_overlap entities
      - they are not already in a supersedes relationship (caller
        suppresses by ordering: supersedes plan first; conflict plan
        excludes those pairs)

    Returns plans for the curation phase to act on.
    """
    plans: list[ConflictPlan] = []
    seen_pairs: set[tuple[int, int]] = set()
    for c in claims:
        c_id = c.get("id")
        c_type = c.get("claim_type")
        c_entities = set(c.get("entity_ids") or [])
        if not c_id or not c_type or not c_entities:
            continue
        if c.get("supersedes"):
            continue
        for eid in c_entities:
            for prior in prior_claims_by_entity.get(eid, []):
                p_id = prior.get("id")
                if not p_id or p_id == c_id:
                    continue
                pair_key = (min(c_id, p_id), max(c_id, p_id))
                if pair_key in seen_pairs:
                    continue
                if prior.get("supersedes") == c_id or c.get("supersedes") == p_id:
                    continue
                reason = _conflict_reason(c_type, prior.get("claim_type", ""))
                if not reason:
                    continue
                p_entities = set(prior.get("entity_ids") or [])
                overlap = sorted(c_entities & p_entities)
                if len(overlap) < min_entity_overlap:
                    continue
                plans.append(
                    ConflictPlan(
                        claim_a_id=pair_key[0],
                        claim_b_id=pair_key[1],
                        overlap_entities=overlap,
                        reason=reason,
                    )
                )
                seen_pairs.add(pair_key)
    return plans


# ── Public resolver entry point ───────────────────────────────────────


def resolve(
    claims: list[dict],
    *,
    entities_by_memory: dict[int, list[int]],
    prior_claims_by_entity: dict[int, list[dict]],
    entity_name_to_id: dict[str, int] | None = None,
) -> tuple[
    list[EntityLinkPlan],
    list[SupersedesPlan],
    list[ConflictPlan],
    ResolveStats,
]:
    """Compute all three resolution plans for a batch of claims.

    Pre-fetched inputs from the handler:
      - entities_by_memory[memory_id] → list of entity_ids
      - prior_claims_by_entity[entity_id] → list of prior claim dicts
        (already enriched with entity_ids from a pre-pass)
      - entity_name_to_id — lowercased name → entity_id

    Order matters: entity links first (so supersedes/conflicts can
    use the freshly-attached ids), then supersedes (so conflict
    detection can suppress superseded pairs).
    """
    link_plans = plan_entity_links(claims, entities_by_memory, entity_name_to_id)

    # Inject the planned entity ids back into the claim dicts so
    # supersedes/conflict planners see the up-to-date data.
    plan_by_claim: dict[int, list[int]] = {p.claim_id: p.entity_ids for p in link_plans}
    enriched: list[dict] = []
    for c in claims:
        c2 = dict(c)
        c2["entity_ids"] = plan_by_claim.get(c["id"], c.get("entity_ids") or [])
        enriched.append(c2)

    sup_plans = plan_supersedes(enriched, prior_claims_by_entity)

    # Build a set of superseded ids so conflict detection can skip them
    superseded_ids: set[int] = {p.superseded_claim_id for p in sup_plans}
    superseder_ids: set[int] = {p.new_claim_id for p in sup_plans}
    conflict_input = [
        c
        for c in enriched
        if c["id"] not in superseded_ids and c["id"] not in superseder_ids
    ]

    conf_plans = plan_conflicts(conflict_input, prior_claims_by_entity)

    stats = ResolveStats(
        claims_processed=len(claims),
        entity_links_planned=sum(1 for p in link_plans if p.entity_ids),
        supersedes_planned=len(sup_plans),
        conflicts_planned=len(conf_plans),
    )
    return link_plans, sup_plans, conf_plans, stats
