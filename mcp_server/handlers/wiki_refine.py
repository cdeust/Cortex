"""Wiki Phase 2.3 (Path B) — LLM-augmented draft refinement.

Two MCP tools:

  wiki_get_draft(draft_id) — returns the draft, the originating claims,
                             and the kind's autofill prompt + section
                             contract. Claude reads this to do its work.

  wiki_refine_draft(draft_id, ...) — Claude submits a refined lead,
                                     sections, and optionally a new
                                     title. Updates wiki.drafts in place.
                                     Records a memo with the prompt
                                     hash so the audit trail can
                                     differentiate template vs LLM
                                     synthesis.

Path A (template synthesizer) populates wiki.drafts at scale.
Path B is the per-draft refinement that turns a routed-claim skeleton
into prose. Caller (Claude) owns the writing; the server enforces
schema and audit.

Composition root only — no synthesis logic lives here. The LLM IS
the synthesis logic in Path B; the server just brokers inputs and
records outputs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_schema_loader import load_registry
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    get_draft,
    insert_memo,
    list_drafts,
    update_draft,
)


# ── Tool: wiki_get_draft ──────────────────────────────────────────────


schema_get = {
    "description": (
        "Fetch a draft + its source claims + the kind contract so the "
        "caller (LLM) can refine it. Phase 2.3 (Path B)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "draft_id": {"type": "integer"},
            "list_pending": {
                "type": "boolean",
                "default": False,
                "description": "If true, list pending drafts instead of fetching one.",
            },
            "kind": {
                "type": "string",
                "description": "Filter list by kind when list_pending=true.",
            },
            "limit": {"type": "integer", "default": 20},
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


def _claims_for_memory(conn, memory_id: int) -> list[dict]:
    sql = """
    SELECT id, text, claim_type, entity_ids, evidence_refs, confidence
      FROM wiki.claim_events WHERE memory_id = %s ORDER BY id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (memory_id,))
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        else:
            out.append(
                {
                    "id": r[0],
                    "text": r[1],
                    "claim_type": r[2],
                    "entity_ids": r[3] or [],
                    "evidence_refs": r[4] or [],
                    "confidence": r[5],
                }
            )
    return out


def _kind_contract(registry, kind: str) -> dict:
    """Return the structural contract for a kind: required + optional
    sections plus the autofill prompt string the LLM should follow.
    """
    kdef = registry.kinds.get(kind)
    if kdef is None:
        return {
            "kind": kind,
            "display_name": kind,
            "required_sections": [],
            "optional_sections": [],
            "autofill_prompt": "",
        }
    return {
        "kind": kdef.name,
        "display_name": kdef.display_name,
        "required_sections": list(kdef.required_sections),
        "optional_sections": list(kdef.optional_sections),
        "autofill_prompt": kdef.autofill_prompt,
    }


async def handler_get(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    store = _get_store()
    conn = store._conn
    registry = load_registry(Path(WIKI_ROOT))

    if args.get("list_pending"):
        drafts = list_drafts(
            conn,
            status="pending",
            kind=args.get("kind"),
            limit=int(args.get("limit", 20)),
        )
        # Trim payload — return enough for the caller to pick which to refine
        return {
            "drafts": [
                {
                    "id": d["id"],
                    "kind": d["kind"],
                    "title": d["title"],
                    "lead": d["lead"][:200],
                    "memory_id": d["memory_id"],
                    "concept_id": d["concept_id"],
                    "confidence": d["confidence"],
                    "synth_model": d["synth_model"],
                }
                for d in drafts
            ],
            "count": len(drafts),
        }

    draft_id = args.get("draft_id")
    if draft_id is None:
        return {"error": "draft_id required (or list_pending=true)"}

    draft = get_draft(conn, int(draft_id))
    if draft is None:
        return {"error": f"draft {draft_id} not found"}

    # Source claims (only when memory-backed)
    claims: list[dict] = []
    if draft.get("memory_id"):
        claims = _claims_for_memory(conn, draft["memory_id"])

    return {
        "draft": {
            "id": draft["id"],
            "memory_id": draft["memory_id"],
            "concept_id": draft["concept_id"],
            "kind": draft["kind"],
            "title": draft["title"],
            "lead": draft["lead"],
            "sections": draft["sections"],
            "frontmatter": draft["frontmatter"],
            "confidence": draft["confidence"],
            "synth_model": draft["synth_model"],
            "status": draft["status"],
        },
        "kind_contract": _kind_contract(registry, draft["kind"]),
        "source_claims": [
            {
                "id": c["id"],
                "claim_type": c["claim_type"],
                "text": c["text"],
                "confidence": c["confidence"],
                "evidence_refs": c["evidence_refs"],
            }
            for c in claims
        ],
        "instructions": (
            "Refine the draft to satisfy the kind_contract. "
            "Each required_section must be filled with prose grounded in "
            "the source_claims. The lead must be ≤60 words and self-contained. "
            "Use [[slug]] syntax to link to other wiki pages where appropriate. "
            "When done, call wiki_refine_draft with the new lead and sections."
        ),
    }


# ── Tool: wiki_refine_draft ───────────────────────────────────────────


schema_refine = {
    "description": (
        "Submit a refined draft (lead, sections, optional title). Updates "
        "wiki.drafts in place; records an audit memo. Phase 2.3 (Path B)."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["draft_id"],
        "properties": {
            "draft_id": {"type": "integer"},
            "title": {"type": "string"},
            "lead": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["heading", "body"],
                    "properties": {
                        "heading": {"type": "string"},
                        "body": {"type": "string"},
                        "claim_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                },
            },
            "frontmatter": {"type": "object"},
            "synth_model": {
                "type": "string",
                "default": "claude_refine_v1",
                "description": "Identifier for the refinement model/method.",
            },
            "synth_prompt": {
                "type": "string",
                "description": "Optional copy of the refinement prompt for audit.",
            },
            "rationale": {
                "type": "string",
                "description": "Optional explanation of what was changed and why.",
            },
        },
    },
}


def _validate_against_contract(
    sections: list[dict], required_sections: list[str]
) -> list[str]:
    """Return a list of human-readable validation errors."""
    errors: list[str] = []
    headings = {s.get("heading", "").strip() for s in sections}
    for req in required_sections:
        if req not in headings:
            errors.append(f"required section missing: {req!r}")
    for s in sections:
        if not s.get("body", "").strip():
            errors.append(f"section {s.get('heading')!r} has empty body")
    return errors


async def handler_refine(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    draft_id = args.get("draft_id")
    if draft_id is None:
        return {"error": "draft_id required"}

    store = _get_store()
    conn = store._conn

    draft = get_draft(conn, int(draft_id))
    if draft is None:
        return {"error": f"draft {draft_id} not found"}

    sections = args.get("sections")
    if sections is not None:
        registry = load_registry(Path(WIKI_ROOT))
        contract = _kind_contract(registry, draft["kind"])
        validation_errors = _validate_against_contract(
            sections, contract["required_sections"]
        )
        if validation_errors:
            return {
                "error": "validation failed",
                "validation_errors": validation_errors,
                "kind_contract": contract,
            }

    synth_model = args.get("synth_model", "claude_refine_v1")
    synth_prompt = args.get("synth_prompt")
    prompt_hash = (
        hashlib.sha256(synth_prompt.encode("utf-8")).hexdigest()[:16]
        if synth_prompt
        else None
    )

    updated = update_draft(
        conn,
        int(draft_id),
        title=args.get("title"),
        lead=args.get("lead"),
        sections=sections,
        frontmatter=args.get("frontmatter"),
        synth_model=synth_model,
        synth_prompt=synth_prompt,
        confidence=0.85,  # LLM-refined drafts get a confidence bump
    )

    if updated:
        rationale = args.get("rationale") or (
            f"LLM-refined draft. Model: {synth_model}. "
            f"Prompt hash: {prompt_hash or 'n/a'}."
        )
        insert_memo(
            conn,
            subject_type="draft",
            subject_id=int(draft_id),
            decision="refined_llm",
            rationale=rationale,
            inputs={"synth_model": synth_model, "synth_prompt_hash": prompt_hash},
            confidence=0.85,
            author="claude_refine",
        )
        conn.commit()

    return {
        "draft_id": int(draft_id),
        "updated": updated,
        "synth_model": synth_model,
        "synth_prompt_hash": prompt_hash,
    }
