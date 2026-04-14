"""Wiki Phase 3 — Concept emergence sweep.

Run incremental clustering over resolved claim_events. Insert new
candidate concepts; update existing concepts with fresh claims;
transition status (candidate → saturating → promoted) per the
saturation rules.

Modes:
  full sweep:   wiki_emerge({})
  partial:      wiki_emerge({"limit": 1000})  — process only N claims
  diagnostics:  wiki_emerge({"dry_run": true})

Composition root only. Pure logic in core/concept_emerger.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.concept_emerger import emerge
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    get_concepts_by_entity_overlap,
    insert_concept,
    insert_memo,
    update_concept,
)


schema = {
    "description": (
        "Run a concept emergence pass. Clusters resolved claim_events "
        "by entity overlap, computes axial slots and saturation, "
        "promotes saturated concepts to ready-for-synthesis status. "
        "Phase 3 of the redesign pipeline."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 5000,
                "description": "Max claims to load for clustering.",
            },
            "dry_run": {
                "type": "boolean",
                "default": False,
                "description": "Compute plans without persisting them.",
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _fetch_resolved_claims(conn, limit: int) -> list[dict]:
    """Pull claim_events that have at least one entity_id."""
    sql = """
    SELECT id, memory_id, text, claim_type, entity_ids, extracted_at
      FROM wiki.claim_events
     WHERE entity_ids IS NOT NULL
       AND array_length(entity_ids, 1) > 0
     ORDER BY id
     LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append(
                {
                    "id": r[0],
                    "memory_id": r[1],
                    "text": r[2],
                    "claim_type": r[3],
                    "entity_ids": r[4] or [],
                    "extracted_at": r[5],
                }
            )
    return out


def _existing_concepts_index(conn, entity_ids: list[int]) -> dict[int, dict]:
    """Build a mapping center_entity_id → existing concept row.

    The emerger uses entity overlap to match its clusters to existing
    concepts. Indexing by every entity_id present in the existing
    concepts gives O(1) overlap probing.
    """
    rows = get_concepts_by_entity_overlap(conn, entity_ids)
    out: dict[int, dict] = {}
    for r in rows:
        for eid in r.get("entity_ids") or []:
            # Each entity points to its concept (first wins on duplicate)
            out.setdefault(eid, r)
    return out


def _persist_plan(conn, plan, dry_run: bool) -> tuple[int, str]:
    """Persist one ConceptPlan. Returns (concept_id, action)."""
    if dry_run:
        return (plan.concept_id or -1, "dry_run")

    if plan.concept_id is None:
        new_id = insert_concept(
            conn,
            {
                "label": plan.label,
                "status": plan.status,
                "entity_ids": plan.entity_ids,
                "grounding_memory_ids": plan.grounding_memory_ids,
                "grounding_claim_ids": plan.grounding_claim_ids,
                "properties": plan.properties,
                "axial_slots": plan.axial_slots,
                "saturation_rate": plan.saturation_rate,
                "saturation_streak": plan.saturation_streak,
            },
        )
        insert_memo(
            conn,
            subject_type="concept",
            subject_id=new_id,
            decision="emerged",
            rationale=(
                f"New candidate concept around entity-cluster of "
                f"{len(plan.entity_ids)} entities, "
                f"{len(plan.grounding_memory_ids)} memories"
            ),
            inputs={"label": plan.label, "status": plan.status},
            confidence=0.5,
            author="emerger",
        )
        return (new_id, "inserted")

    update_concept(
        conn,
        plan.concept_id,
        {
            "label": plan.label,
            "status": plan.status,
            "entity_ids": plan.entity_ids,
            "grounding_memory_ids": plan.grounding_memory_ids,
            "grounding_claim_ids": plan.grounding_claim_ids,
            "properties": plan.properties,
            "axial_slots": plan.axial_slots,
            "saturation_rate": plan.saturation_rate,
            "saturation_streak": plan.saturation_streak,
            "last_property_at": True,  # special key triggers NOW()
        },
    )
    insert_memo(
        conn,
        subject_type="concept",
        subject_id=plan.concept_id,
        decision="updated",
        rationale=(
            f"Concept absorbed new claims; status={plan.status}; "
            f"saturation_streak={plan.saturation_streak}; "
            f"grounding_memories={len(plan.grounding_memory_ids)}"
        ),
        inputs={"saturation_rate": plan.saturation_rate},
        confidence=0.6,
        author="emerger",
    )
    return (plan.concept_id, "updated")


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    limit = int(args.get("limit", 5000))
    dry_run = bool(args.get("dry_run", False))

    store = _get_store()
    conn = store._conn

    claims = _fetch_resolved_claims(conn, limit)
    if not claims:
        return {
            "claims_loaded": 0,
            "concepts_inserted": 0,
            "concepts_updated": 0,
            "note": "no resolved claims found",
        }

    # Pre-fetch existing concepts that touch any of these entities
    candidate_entities = sorted(
        {eid for c in claims for eid in (c.get("entity_ids") or [])}
    )
    existing_index = _existing_concepts_index(conn, candidate_entities)

    plans, stats = emerge(claims=claims, existing_concepts_by_entities=existing_index)

    inserted = 0
    updated = 0
    promoted_ids: list[int] = []
    saturating_ids: list[int] = []

    for plan in plans:
        cid, action = _persist_plan(conn, plan, dry_run)
        if action == "inserted":
            inserted += 1
        elif action == "updated":
            updated += 1
        if plan.status == "promoted":
            promoted_ids.append(cid)
        elif plan.status == "saturating":
            saturating_ids.append(cid)

    if not dry_run:
        conn.commit()

    return {
        "claims_loaded": len(claims),
        "claims_grouped": stats.claims_grouped,
        "candidate_concepts": stats.candidate_concepts,
        "concepts_inserted": inserted,
        "concepts_updated": updated,
        "concepts_promoted": stats.promoted,
        "concepts_saturating": stats.saturating,
        "promoted_concept_ids": promoted_ids[:20],
        "saturating_concept_ids": saturating_ids[:20],
        "dry_run": dry_run,
    }
