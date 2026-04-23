"""Handler: rate_memory — provide usefulness feedback for a memory.

Increments useful_count when a memory was helpful, then recomputes
metamemory confidence (useful_count / access_count). High-confidence
memories resist decay and rank higher in future recalls.

When the caller supplies the ``query`` that surfaced the memory, the
handler also records a (raw_ce_score, useful) training sample for the
reranker's Platt calibrator (AF-2). Without ``query``, only the
metamemory update happens — identical to the pre-AF-2 behaviour.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import reranker, reranker_calibration, thermodynamics
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Rate memory",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Record a usefulness verdict for a memory that just surfaced in "
        "recall: increments useful_count when helpful and recomputes "
        "metamemory confidence as useful_count / access_count "
        "(Nelson & Narens 1990 framework). High-confidence memories resist "
        "heat decay and rank higher in future recalls; persistently "
        "unhelpful memories drift toward archival. Use this whenever a "
        "recalled memory either solved the problem or wasted attention — "
        "the feedback loop is what keeps recall accurate. Distinct from "
        "`forget` (deletes), `anchor` (pins, doesn't score), and "
        "`validate_memory` (filesystem-ref staleness, not user verdict). "
        "Mutates the memories table (access_count, useful_count, "
        "confidence). Latency ~20ms. Returns {rated, memory_id, useful, "
        "access_count, useful_count, confidence, content_preview}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["memory_id", "useful"],
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Integer ID of the memory to rate (returned by recall).",
                "minimum": 1,
                "examples": [42, 1024],
            },
            "useful": {
                "type": "boolean",
                "description": (
                    "true if the memory was helpful for the current task; "
                    "false if it was noise or misleading."
                ),
                "examples": [True, False],
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional: the query that surfaced this memory. When "
                    "provided, the handler records a (raw_ce_score, useful) "
                    "sample for the reranker's Platt calibrator "
                    "(AF-2 feedback loop). Omit if the memory was not "
                    "surfaced by a recall call."
                ),
                "examples": ["authentication middleware", "error retry logic"],
            },
        },
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────


def _record_platt_sample(query: str, content: str, useful: bool) -> bool:
    """Record a (raw_ce_score, useful) sample for AF-2 calibration.

    Returns True iff a sample was actually recorded. No-op (returns False)
    when:
      - query is empty (caller opted out)
      - FlashRank is unavailable (cold environment)
      - the cross-encoder fails to score the pair

    Contract:
      pre:  content is non-empty; useful is a bool.
      post: on True, reranker_calibration._SAMPLES has one more entry and
            a refit may have happened as a side effect of record_rating.
    """
    if not query or not content:
        return False
    raw_ce = reranker.get_raw_ce_score(query, content)
    if raw_ce is None:
        return False
    reranker_calibration.record_rating(raw_ce, useful=useful)
    return True


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rate a memory and update its metamemory confidence.

    Contract:
      pre:  args.memory_id refers to an existing memory; args.useful is a bool.
      post: the memory's (access_count, useful_count, confidence) is updated
            via ``update_memory_metamemory``. IF args.query is provided AND
            FlashRank is available, a Platt training pair is also recorded
            via reranker_calibration.record_rating; this may trigger a refit.
    """
    if not args or args.get("memory_id") is None:
        return {"rated": False, "reason": "no_memory_id"}
    if args.get("useful") is None:
        return {"rated": False, "reason": "missing useful flag"}

    memory_id = int(args["memory_id"])
    useful = bool(args["useful"])
    query = args.get("query", "") or ""

    store = _get_store()
    mem = store.get_memory(memory_id)
    if mem is None:
        return {"rated": False, "reason": "not_found", "memory_id": memory_id}

    access_count = mem.get("access_count", 0) + 1
    useful_count = mem.get("useful_count", 0) + (1 if useful else 0)

    # Recompute metamemory confidence
    confidence = thermodynamics.compute_metamemory_confidence(
        access_count, useful_count
    )
    if confidence is None:
        confidence = mem.get("confidence", 1.0)  # Not enough data yet

    store.update_memory_metamemory(memory_id, access_count, useful_count, confidence)

    # AF-2: collect Platt training sample when caller provided the surfacing
    # query. Silent best-effort — metamemory update is the primary contract.
    platt_recorded = _record_platt_sample(query, mem.get("content", ""), useful)

    response: dict[str, Any] = {
        "rated": True,
        "memory_id": memory_id,
        "useful": useful,
        "access_count": access_count,
        "useful_count": useful_count,
        "confidence": round(confidence, 4),
        "content_preview": mem["content"][:80],
    }
    if platt_recorded:
        response["platt_sample_recorded"] = True
        response["platt_sample_count"] = reranker_calibration.sample_count()
    return response
