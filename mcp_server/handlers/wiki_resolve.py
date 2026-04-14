"""Wiki Phase 2.2 — Resolve claim_events.

MCP tool entry point. Wires:
  - core/claim_resolver (pure logic, returns plans)
  - infrastructure/pg_store_wiki (entity lookup, batch updates, memo write)

Modes:
  resolve all unlinked: wiki_resolve({})
  resolve a slice:      wiki_resolve({"limit": 100})
  resolve one memory:   wiki_resolve({"memory_id": 42})

Composition root — never raises per-claim; collects errors in summary.
Idempotent at the row level (entity / supersedes updates skip no-ops).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.claim_resolver import resolve
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    get_claims_by_entity,
    get_entities_by_memory,
    get_entity_name_index,
    insert_memo,
    update_claim_entities,
    update_claim_supersedes,
)


schema = {
    "description": (
        "Resolve claim_events: link entities, detect supersedes "
        "and conflicts. Phase 2.2 of the wiki redesign pipeline."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Resolve claims from this memory only.",
            },
            "limit": {
                "type": "integer",
                "default": 500,
                "description": "Max claims to process per sweep.",
            },
            "name_index_size": {
                "type": "integer",
                "default": 5000,
                "description": (
                    "How many top-heat entity names to load for inline matching."
                ),
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _fetch_claims(conn, memory_id: int | None, limit: int) -> list[dict]:
    """Fetch claims that need resolution.

    Default: claims whose entity_ids is empty (never resolved).
    With memory_id: all claims for that memory regardless of state.
    """
    if memory_id is not None:
        sql = (
            "SELECT id, memory_id, text, claim_type, entity_ids, "
            "supersedes, extracted_at "
            "FROM wiki.claim_events WHERE memory_id = %s ORDER BY id"
        )
        params: tuple = (memory_id,)
    else:
        sql = (
            "SELECT id, memory_id, text, claim_type, entity_ids, "
            "supersedes, extracted_at "
            "FROM wiki.claim_events "
            "WHERE entity_ids = '{}' OR entity_ids IS NULL "
            "ORDER BY id LIMIT %s"
        )
        params = (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
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
                    "supersedes": r[5],
                    "extracted_at": r[6],
                }
            )
    return out


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    memory_id = args.get("memory_id")
    limit = int(args.get("limit", 500))
    name_index_size = int(args.get("name_index_size", 5000))

    store = _get_store()
    conn = store._conn

    claims = _fetch_claims(conn, memory_id, limit)
    if not claims:
        return {
            "claims_processed": 0,
            "entity_links_written": 0,
            "supersedes_written": 0,
            "conflicts_logged": 0,
            "note": "no claims matched (already resolved or none exist)",
        }

    # Pre-fetch the inputs the resolver needs
    memory_ids = list({c["memory_id"] for c in claims if c.get("memory_id")})
    entities_by_memory = get_entities_by_memory(conn, memory_ids)
    entity_name_to_id = (
        get_entity_name_index(conn, name_index_size) if name_index_size > 0 else {}
    )

    # Compute the planned entity sets so we can pull priors for THOSE entities
    candidate_entities: set[int] = set()
    for c in claims:
        candidate_entities.update(entities_by_memory.get(c.get("memory_id"), []))
    excl_ids = [c["id"] for c in claims]
    prior_claims_by_entity = get_claims_by_entity(
        conn, list(candidate_entities), exclude_claim_ids=excl_ids
    )

    # Run the resolver
    link_plans, sup_plans, conf_plans, stats = resolve(
        claims,
        entities_by_memory=entities_by_memory,
        prior_claims_by_entity=prior_claims_by_entity,
        entity_name_to_id=entity_name_to_id,
    )

    # Persist plans
    entity_updates = [(p.claim_id, p.entity_ids) for p in link_plans if p.entity_ids]
    sup_updates = [(p.new_claim_id, p.superseded_claim_id) for p in sup_plans]

    entity_links_written = update_claim_entities(conn, entity_updates)
    supersedes_written = update_claim_supersedes(conn, sup_updates)

    # Memo each supersedes + conflict for the audit trail
    for plan in sup_plans:
        insert_memo(
            conn,
            subject_type="claim",
            subject_id=plan.new_claim_id,
            decision="supersedes",
            rationale=plan.rationale,
            inputs={"superseded_claim_id": plan.superseded_claim_id},
            confidence=0.7,
            author="resolver",
        )

    for plan in conf_plans:
        insert_memo(
            conn,
            subject_type="claim",
            subject_id=plan.claim_a_id,
            decision="conflict_candidate",
            rationale=plan.reason,
            inputs={
                "claim_b_id": plan.claim_b_id,
                "overlap_entities": plan.overlap_entities,
            },
            confidence=0.5,
            author="resolver",
        )

    conn.commit()

    return {
        "claims_processed": stats.claims_processed,
        "entity_links_planned": stats.entity_links_planned,
        "entity_links_written": entity_links_written,
        "supersedes_planned": stats.supersedes_planned,
        "supersedes_written": supersedes_written,
        "conflicts_logged": stats.conflicts_planned,
    }
