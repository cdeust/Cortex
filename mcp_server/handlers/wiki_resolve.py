"""Wiki Phase 2.2 — Resolve claim_events.

MCP tool entry point. Wires:
  - core/claim_resolver (pure logic, returns plans)
  - infrastructure/pg_store_wiki (entity lookup, batch updates, memo write)

Modes:
  resolve all unlinked: wiki_resolve({})
  resolve a slice:      wiki_resolve({"limit": 100})
  resolve one memory:   wiki_resolve({"memory_id": 42})

source: ADR-0470"""

from __future__ import annotations

from typing import Any

from mcp_server.core.claim_resolver import resolve
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.wiki_handler_queries import claims_needing_resolution
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
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
        "Attach entity_ids to unresolved claim_events, detect supersedes "
        "relationships against prior claims for the same entities, and log "
        "conflict candidates. Phase 2.2 of the wiki redesign pipeline; runs "
        "after `wiki_extract` and before `wiki_emerge`. Reads "
        "wiki.claim_events plus the entity name index; writes entity_ids, "
        "supersedes pointers, and audit memos. Idempotent — already-resolved "
        "rows are skipped unless memory_id is given. Distinct from "
        "`wiki_extract` which creates the rows, and from `wiki_emerge` which "
        "clusters resolved claims into concepts. Latency ~100ms per 100 "
        "claims. Returns {claims_processed, entity_links_written, "
        "supersedes_written, conflicts_logged}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": (
                    "Resolve every claim_event for this memory regardless of "
                    "current entity_ids state. Omit to sweep only unresolved "
                    "claims (entity_ids empty)."
                ),
                "minimum": 1,
                "examples": [42, 1024],
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Max unresolved claims to process per sweep. Ignored when "
                    "memory_id is given."
                ),
                "default": 500,
                "minimum": 1,
                "maximum": 10000,
                "examples": [200, 500, 2000],
            },
            "name_index_size": {
                "type": "integer",
                "description": (
                    "How many top-heat entity names to preload for inline string "
                    "matching during resolution. Higher values catch more "
                    "mentions at the cost of memory."
                ),
                "default": 5000,
                "minimum": 0,
                "maximum": 50000,
                "examples": [1000, 5000, 20000],
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    memory_id = args.get("memory_id")
    limit = int(args.get("limit", 500))
    name_index_size = int(args.get("name_index_size", 5000))

    store = _get_store()

    claims = store.call(claims_needing_resolution, memory_id, limit)
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
    entities_by_memory = store.call(get_entities_by_memory, memory_ids)
    entity_name_to_id = (
        store.call(get_entity_name_index, name_index_size)
        if name_index_size > 0
        else {}
    )

    # Compute the planned entity sets so we can pull priors for THOSE entities
    candidate_entities: set[int] = set()
    for c in claims:
        claim_memory_id = c.get("memory_id")
        if claim_memory_id is not None:
            candidate_entities.update(entities_by_memory.get(claim_memory_id, []))
    excl_ids = [c["id"] for c in claims]
    prior_claims_by_entity = store.call(
        get_claims_by_entity, list(candidate_entities), exclude_claim_ids=excl_ids
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

    entity_links_written = store.call(update_claim_entities, entity_updates)
    supersedes_written = store.call(update_claim_supersedes, sup_updates)

    # source: ADR-0470
    for plan in sup_plans:
        store.call(
            insert_memo,
            subject_type="claim",
            subject_id=plan.new_claim_id,
            decision="supersedes",
            rationale=plan.rationale,
            inputs={"superseded_claim_id": plan.superseded_claim_id},
            confidence=0.7,
            author="resolver",
        )

    for plan in conf_plans:
        store.call(
            insert_memo,
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

    return {
        "claims_processed": stats.claims_processed,
        "entity_links_planned": stats.entity_links_planned,
        "entity_links_written": entity_links_written,
        "supersedes_planned": stats.supersedes_planned,
        "supersedes_written": supersedes_written,
        "conflicts_logged": stats.conflicts_planned,
    }
