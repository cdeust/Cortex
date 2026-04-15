"""Wiki Phase 2.4 — Curate pending drafts.

Two modes:

  Auto-sweep (default): scan all pending drafts, evaluate each via
  draft_curator, transition status (pending → approved / rejected),
  leave 'hold' drafts untouched for refinement.

  Manual decision: wiki_curate({draft_id: 42, decision: "approved"})
  forces a verdict regardless of the rule gate. Used when the user
  has reviewed a draft personally.

Composition root — wires draft_curator (pure logic) + pg_store_wiki
(status update + memo). Never raises per-draft; collects errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.core.draft_curator import evaluate_draft
from mcp_server.core.wiki_schema_loader import load_registry
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    insert_memo,
    list_drafts,
    update_draft_status,
)


schema = {
    "description": (
        "Decide whether each pending wiki draft is ready to publish. "
        "Auto-sweep mode (default): score every pending draft against its "
        "kind's rule-gate (claim count, section coverage, confidence "
        "threshold) and transition pending → approved | rejected; drafts "
        "that score in the middle stay 'hold' for refinement. Manual mode: "
        "supply draft_id + decision to force a verdict. Phase 2.4 of the "
        "wiki redesign pipeline; runs after `wiki_synthesize`, before "
        "`wiki_compile`. Mutates wiki.drafts.status and writes audit memos. "
        "Distinct from `wiki_compile` which actually publishes the approved "
        "drafts. Latency ~10ms per draft. Returns {drafts_evaluated, "
        "approved, rejected, held, sample_held, errors}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "draft_id": {
                "type": "integer",
                "description": (
                    "Manual mode: target a single draft by id. Pair with "
                    "`decision` to force the verdict, bypassing the rule gate."
                ),
                "minimum": 1,
                "examples": [42, 1024],
            },
            "decision": {
                "type": "string",
                "description": (
                    "Manual verdict for the targeted draft_id. Required when "
                    "draft_id is given; ignored otherwise."
                ),
                "enum": ["approved", "rejected"],
                "examples": ["approved", "rejected"],
            },
            "reason": {
                "type": "string",
                "description": (
                    "Free-text justification recorded in the audit memo. "
                    "Strongly recommended for manual decisions."
                ),
                "examples": [
                    "Reviewed against ADR-0042; matches the canonical decision",
                    "Stale claim_events — superseded by memory 5123",
                ],
            },
            "limit": {
                "type": "integer",
                "description": ("Max pending drafts to evaluate per auto-sweep call."),
                "default": 200,
                "minimum": 1,
                "maximum": 5000,
                "examples": [100, 200, 1000],
            },
            "kind": {
                "type": "string",
                "description": (
                    "Restrict the auto-sweep to one wiki kind (e.g. only "
                    "ADRs). Must match a kind in the wiki schema registry."
                ),
                "examples": ["adr", "lesson", "spec", "note"],
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    store = _get_store()
    conn = store._conn
    registry = load_registry(Path(WIKI_ROOT))

    # Manual decision path
    if args.get("draft_id") is not None and args.get("decision"):
        draft_id = int(args["draft_id"])
        decision = args["decision"]
        reason = args.get("reason", "manual decision via wiki_curate")
        ok = update_draft_status(conn, draft_id, status=decision)
        if not ok:
            return {"error": f"draft {draft_id} not found"}
        insert_memo(
            conn,
            subject_type="draft",
            subject_id=draft_id,
            decision=decision,
            rationale=reason,
            confidence=1.0,
            author="user_manual",
        )
        conn.commit()
        return {"draft_id": draft_id, "verdict": decision, "manual": True}

    # Auto-sweep path
    pending = list_drafts(
        conn,
        status="pending",
        kind=args.get("kind"),
        limit=int(args.get("limit", 200)),
    )

    counts: dict[str, int] = {"approved": 0, "rejected": 0, "hold": 0}
    errors: list[str] = []
    sample_holds: list[dict] = []

    for d in pending:
        try:
            kdef = registry.kinds.get(d["kind"])
            decision = evaluate_draft(d, kdef)
            if decision.verdict == "hold":
                counts["hold"] += 1
                if len(sample_holds) < 5:
                    sample_holds.append(
                        {
                            "id": d["id"],
                            "score": round(decision.score, 2),
                            "reasons": list(decision.reasons),
                        }
                    )
                continue

            update_draft_status(conn, d["id"], status=decision.verdict)
            insert_memo(
                conn,
                subject_type="draft",
                subject_id=d["id"],
                decision=decision.verdict,
                rationale=" | ".join(decision.reasons)
                if decision.reasons
                else "all rule-gate checks passed",
                inputs={"score": round(decision.score, 3)},
                confidence=decision.score,
                author="curator_auto",
            )
            counts[decision.verdict] += 1
        except Exception as e:
            errors.append(f"draft {d.get('id')}: {e}")

    conn.commit()
    return {
        "drafts_evaluated": len(pending),
        "approved": counts["approved"],
        "rejected": counts["rejected"],
        "held": counts["hold"],
        "sample_held": sample_holds,
        "errors": errors[:10],
        "error_count": len(errors),
    }
