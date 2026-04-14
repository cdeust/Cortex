"""Wiki Phase 2.3 (Path A) — Template-driven draft synthesis.

For each source memory that has resolved claim_events but no existing
draft, build a DraftPage by:
  - Choosing a target kind from the dominant claim_type (or hint)
  - Routing claims to kind-specific sections (default routing map)
  - Picking the highest-confidence claim as the lead
  - Persisting to wiki.drafts with status='pending'

Modes:
  synthesize all unsynthesized:  wiki_synthesize({})
  synthesize one memory:         wiki_synthesize({"memory_id": 42})
  synthesize for a concept:      wiki_synthesize({"concept_id": 7})  # Phase 3
  force re-synthesis:            wiki_synthesize({"memory_id": 42, "force": true})

Composition root — wires synthesizer + DB ops + kind registry.
Never raises per-source; collects errors in summary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.draft_synthesizer import synthesize_draft
from mcp_server.core.wiki_schema_loader import load_registry
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    find_draft_for_source,
    insert_draft,
    insert_memo,
    update_draft,
)


schema = {
    "description": (
        "Template-synthesize wiki drafts from resolved claim_events. "
        "Phase 2.3 (Path A) of the redesign pipeline."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {"type": "integer"},
            "concept_id": {"type": "integer"},
            "force": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 100},
            "kind_hint": {
                "type": "string",
                "description": (
                    "Force a target kind. Otherwise inferred from the "
                    "dominant claim_type."
                ),
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


# ── Kind inference ────────────────────────────────────────────────────


_TYPE_TO_KIND_AFFINITY: dict[str, str] = {
    "decision": "adr",
    "limitation": "lesson",
    "method": "spec",
    "result": "spec",
    "observation": "note",
    "question": "note",
    "reference": "note",
    "assertion": "note",
}


def _infer_kind(claims: list[dict], available_kinds: set[str]) -> str:
    """Pick a target kind from the dominant claim_type."""
    if not claims:
        return "note"
    counts: dict[str, int] = {}
    for c in claims:
        kind = _TYPE_TO_KIND_AFFINITY.get(c.get("claim_type", ""), "note")
        counts[kind] = counts.get(kind, 0) + 1
    # Prefer adr / lesson / convention over note when present
    for preferred in ("adr", "lesson", "convention", "spec", "note"):
        if counts.get(preferred):
            if not available_kinds or preferred in available_kinds:
                return preferred
    return "note"


# ── Source enumeration ────────────────────────────────────────────────


def _candidate_memories(conn, memory_id, force, limit) -> list[int]:
    """Return memory_ids that have claims and need a draft."""
    if memory_id is not None:
        return [memory_id]
    if force:
        sql = """
        SELECT DISTINCT memory_id FROM wiki.claim_events
         WHERE memory_id IS NOT NULL ORDER BY memory_id LIMIT %s
        """
    else:
        sql = """
        SELECT DISTINCT c.memory_id
          FROM wiki.claim_events c
         WHERE c.memory_id IS NOT NULL
           AND NOT EXISTS (
             SELECT 1 FROM wiki.drafts d
              WHERE d.memory_id = c.memory_id
                AND d.synth_model = 'template_v1'
           )
         ORDER BY c.memory_id LIMIT %s
        """
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        rows = cur.fetchall()
    return [r["memory_id"] if isinstance(r, dict) else r[0] for r in rows]


def _claims_for_memory(conn, memory_id: int) -> list[dict]:
    sql = """
    SELECT id, memory_id, text, claim_type, entity_ids, evidence_refs,
           confidence, supersedes
      FROM wiki.claim_events
     WHERE memory_id = %s
     ORDER BY id
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
                    "memory_id": r[1],
                    "text": r[2],
                    "claim_type": r[3],
                    "entity_ids": r[4] or [],
                    "evidence_refs": r[5] or [],
                    "confidence": r[6],
                    "supersedes": r[7],
                }
            )
    return out


# ── Handler entry ─────────────────────────────────────────────────────


def _draft_to_payload(draft) -> dict:
    """Pydantic DraftPage → dict suitable for insert_draft."""
    return {
        "concept_id": draft.concept_id,
        "memory_id": draft.memory_id,
        "title": draft.title,
        "kind": draft.kind,
        "lead": draft.lead,
        "sections": [
            {"heading": s.heading, "body": s.body, "claim_ids": s.claim_ids}
            for s in draft.sections
        ],
        "frontmatter": draft.frontmatter,
        "provenance": {
            "source_type": draft.provenance.source_type,
            "source_ids": draft.provenance.source_ids,
            "synthesis_model": draft.provenance.synthesis_model,
            "synthesis_prompt_hash": draft.provenance.synthesis_prompt_hash,
        },
        "synth_model": draft.provenance.synthesis_model,
        "confidence": draft.confidence,
        "status": draft.status,
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    memory_id = args.get("memory_id")
    force = bool(args.get("force", False))
    limit = int(args.get("limit", 100))
    kind_hint = args.get("kind_hint")

    store = _get_store()
    conn = store._conn

    # Load kind registry once per call
    registry = load_registry(Path(WIKI_ROOT))
    available_kinds = registry.known_kind_names

    memory_ids = _candidate_memories(conn, memory_id, force, limit)
    if not memory_ids:
        return {
            "drafts_created": 0,
            "drafts_updated": 0,
            "memories_processed": 0,
            "by_kind": {},
            "note": "no memories with claims need synthesis",
        }

    drafts_created = 0
    drafts_updated = 0
    by_kind: dict[str, int] = {}
    errors: list[str] = []

    for mid in memory_ids:
        try:
            claims = _claims_for_memory(conn, mid)
            if not claims:
                continue
            kind = kind_hint or _infer_kind(claims, available_kinds)
            kind_def = registry.kinds.get(kind)
            draft, stats = synthesize_draft(
                claims,
                kind=kind,
                kind_definition=kind_def,
                memory_id=mid,
            )
            payload = _draft_to_payload(draft)

            existing = find_draft_for_source(conn, memory_id=mid)
            if existing and not force:
                # Update in place rather than spawn a duplicate
                update_draft(
                    conn,
                    existing["id"],
                    title=payload["title"],
                    lead=payload["lead"],
                    sections=payload["sections"],
                    frontmatter=payload["frontmatter"],
                    confidence=payload["confidence"],
                    synth_model=payload["synth_model"],
                )
                drafts_updated += 1
                draft_id = existing["id"]
            else:
                draft_id = insert_draft(conn, payload)
                drafts_created += 1

            by_kind[kind] = by_kind.get(kind, 0) + 1

            insert_memo(
                conn,
                subject_type="draft",
                subject_id=draft_id,
                decision="synthesized_template_v1",
                rationale=(
                    f"Routed {stats.claims_routed}/{stats.claims_total} claims "
                    f"into {stats.sections_filled}/{stats.sections_required} "
                    f"required sections."
                ),
                inputs={
                    "memory_id": mid,
                    "kind": kind,
                    "claim_count": len(claims),
                },
                confidence=draft.confidence,
                author="synthesizer_template",
            )
        except Exception as e:
            errors.append(f"memory {mid}: {e}")

    conn.commit()

    return {
        "drafts_created": drafts_created,
        "drafts_updated": drafts_updated,
        "memories_processed": len(memory_ids),
        "by_kind": by_kind,
        "errors": errors[:10],
        "error_count": len(errors),
    }
