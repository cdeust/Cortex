"""Wiki Phase 2.1 — Extract claim_events from memories.

MCP tool entry point. Modes:

    extract one:  wiki_extract({"memory_id": 42})
    extract all:  wiki_extract({})  — sweeps every memory not yet extracted
    re-extract:   wiki_extract({"memory_id": 42, "force": true})

Composition root — wires:
  - core/claim_extractor (pure logic, sentence → ClaimEvent)
  - infrastructure/pg_store_wiki (insert_claim_events, delete_claims_for_memory)
  - infrastructure/memory_store (load memory rows)

Never raises on per-memory errors — collects them and returns in summary.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.claim_extractor import extract_claims
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    delete_claims_for_memory,
    insert_claim_events,
)


schema = {
    "description": (
        "Parse a memory's prose into typed wiki.claim_events rows (assertion, "
        "decision, method, result, observation, question, reference, limitation), "
        "each carrying entity_ids, evidence_refs, confidence, and a supersedes "
        "pointer. Phase 2.1 of the wiki redesign pipeline; the foundational "
        "step every later phase reads from. Pass memory_id to extract one; "
        "omit to sweep all not-yet-extracted memories. Mutates wiki.claim_events. "
        "Distinct from `wiki_resolve` which links these claims to entities, and "
        "from `wiki_synthesize` which renders them into drafts. Latency ~50ms "
        "per memory. Returns {memories_processed, claims_inserted, "
        "claims_per_type, errors}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": (
                    "Extract claims from this single memory only. Omit to sweep "
                    "every memory that has no claim_events yet."
                ),
                "minimum": 1,
                "examples": [42, 1024],
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Re-extract even when claim_events already exist for the "
                    "memory; existing rows for that memory are deleted first."
                ),
                "default": False,
                "examples": [False, True],
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Max memories to process in a single sweep call. Ignored "
                    "when memory_id is given."
                ),
                "default": 200,
                "minimum": 1,
                "maximum": 5000,
                "examples": [100, 200, 1000],
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _memory_rows(conn, memory_id: int | None, limit: int, force: bool) -> list[dict]:
    """Fetch the candidate memory rows for extraction."""
    if memory_id is not None:
        sql = "SELECT id, content, tags FROM memories WHERE id = %s"
        params: tuple = (memory_id,)
    elif force:
        sql = "SELECT id, content, tags FROM memories ORDER BY id LIMIT %s"
        params = (limit,)
    else:
        # Memories without any extracted claim_events yet
        sql = """
        SELECT m.id, m.content, m.tags
          FROM memories m
         WHERE NOT EXISTS (
            SELECT 1 FROM wiki.claim_events c WHERE c.memory_id = m.id
         )
         ORDER BY m.id
         LIMIT %s
        """
        params = (limit,)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(
                {"id": r["id"], "content": r["content"], "tags": r.get("tags") or []}
            )
        else:
            out.append({"id": r[0], "content": r[1], "tags": r[2] or []})
    return out


def _claim_to_dict(claim) -> dict:
    """Pydantic ClaimEvent → dict suitable for insert_claim_events."""
    return {
        "memory_id": claim.memory_id,
        "session_id": claim.session_id,
        "text": claim.text,
        "claim_type": claim.claim_type,
        "entity_ids": claim.entity_ids,
        "evidence_refs": [
            {"kind": r.kind, "target": r.target, "context": r.context}
            for r in claim.evidence_refs
        ],
        "confidence": claim.confidence,
        "supersedes": claim.supersedes,
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    memory_id = args.get("memory_id")
    force = bool(args.get("force", False))
    limit = int(args.get("limit", 200))

    store = _get_store()
    rows = _memory_rows(store._conn, memory_id, limit, force)
    if not rows:
        return {
            "memories_processed": 0,
            "claims_inserted": 0,
            "claims_per_type": {},
            "errors": [],
            "note": "no memories matched (already extracted or no rows)",
        }

    total_claims = 0
    claims_per_type: dict[str, int] = {}
    errors: list[str] = []

    for row in rows:
        try:
            claims, _ = extract_claims(
                row["content"] or "",
                memory_id=row["id"],
                entity_ids=[],  # entity ids attached by Phase 2.2 resolver
            )
            if force or memory_id is not None:
                # Re-extraction: clear prior claims first to avoid duplicates
                delete_claims_for_memory(store._conn, row["id"])
            if not claims:
                continue
            payload = [_claim_to_dict(c) for c in claims]
            insert_claim_events(store._conn, payload)
            total_claims += len(claims)
            for c in claims:
                claims_per_type[c.claim_type] = claims_per_type.get(c.claim_type, 0) + 1
        except Exception as e:
            errors.append(f"memory {row['id']}: {e}")

    store._conn.commit()
    return {
        "memories_processed": len(rows),
        "claims_inserted": total_claims,
        "claims_per_type": claims_per_type,
        "errors": errors[:10],
        "error_count": len(errors),
    }
