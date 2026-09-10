"""Handler: why -- resolve injection receipts into presence evidence.

Locked lexicon: this is evidence of PRESENCE IN CONTEXT — Pearl's
ladder rung 1, recorded associations only — never a causal claim about
what produced an answer.

source: ADR-0452"""

from __future__ import annotations

from typing import Any

from mcp_server.core.response_budget import ListTarget, bound_payload
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.handlers.injection_receipts import INJECTION_CHANNELS
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store

schema = {
    "title": "Why (injection blame: presence-in-context)",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["evidence", "count", "semantics"],
        "properties": {
            "evidence": {
                "type": "array",
                "description": (
                    "Flat presence-in-context evidence, one row per "
                    "(receipt, injected memory) pair. Ordered by recorded "
                    "facts only: emitted_at DESC, receipt id DESC, then the "
                    "injection rank persisted at emission time."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "receipt_id": {"type": "integer"},
                        "channel": {
                            "type": "string",
                            "enum": sorted(INJECTION_CHANNELS),
                            "description": (
                                "Injection channel that emitted the receipt."
                            ),
                        },
                        "session_id": {
                            "type": ["string", "null"],
                            "description": (
                                # source: ADR-0452
                                "Transcript-derived session identity; null for "
                                "receipts "
                                "emitted by the MCP recall handler."
                            ),
                        },
                        "emitted_at": {
                            "type": "string",
                            "description": "Injection instant (ISO 8601).",
                        },
                        "memory_id": {"type": "integer"},
                        "rank": {
                            "type": "integer",
                            "description": (
                                "0-based position in the injected payload, "
                                "persisted at emission — replayed, never "
                                "recomputed."
                            ),
                        },
                        "score": {
                            "type": ["number", "null"],
                            "description": (
                                "Retrieval score at injection time; null for "
                                "channels that do not score (e.g. the "
                                "session_start banner)."
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "Memory body as stored NOW (the receipt "
                                "proves presence, not the byte-exact text "
                                "injected then). Absent when the memory was "
                                "hard-forgotten. Truncated rows keep their "
                                "memory_id — fetch the full body via recall's "
                                "memory_id argument."
                            ),
                        },
                        "memory_missing": {
                            "type": "boolean",
                            "description": (
                                # source: ADR-0452
                                "True when the memory row no longer exists "
                                "(hard-forget after "
                                "injection). The receipt remains valid presence "
                                "evidence."
                            ),
                        },
                        "superseded_by_id": {
                            "type": ["integer", "null"],
                            "description": (
                                "Set when this memory has already been "
                                "corrected by a superseding memory. Surfaced, "
                                "never filtered: the receipt is historical "
                                "evidence of what was in context."
                            ),
                        },
                        "memory_created_at": {"type": ["string", "null"]},
                        "memory_source": {"type": ["string", "null"]},
                        "memory_domain": {"type": ["string", "null"]},
                        "truncated": {
                            "type": "boolean",
                            "description": (
                                "Present and true when content was cut to fit "
                                "the response budget."
                            ),
                        },
                        "content_length": {
                            "type": "integer",
                            "description": (
                                "Original content size (set when truncated)."
                            ),
                        },
                    },
                },
            },
            "count": {
                "type": "integer",
                "description": "Number of evidence rows returned.",
            },
            "receipts_resolved": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Requested receipt ids found in the store.",
            },
            "receipts_unknown": {
                "type": "array",
                "items": {"type": "integer"},
                "description": (
                    "Requested receipt ids with no stored receipt — a typo'd "
                    "marker or a receipt from another store."
                ),
            },
            "semantics": {
                "type": "string",
                "enum": ["presence-in-context"],
                "description": (
                    # source: ADR-0452
                    "Locked lexicon: this response proves what was PRESENT in the "
                    "context, never what CAUSED an answer."
                ),
            },
        },
    },
    "description": (
        # source: ADR-0452
        "Blame path resolver: turn the ⟦rcpt:N⟧ markers visible in "
        "the current context into presence-in-context evidence — "
        "which memories each injection channel (recall, "
        "session_start, auto_recall, agent_briefing) put into the "
        "context, when, at which persisted rank and score. This is "
        "evidence of PRESENCE, never causality. Protocol: collect the "
        "⟦rcpt:N⟧ markers that were in context BEFORE the answer "
        "being questioned; EXCLUDE the marker injected alongside the "
        "current prompt's own memory block (self-pollution guard) — "
        "then pass the ids here. To correct a wrong memory surfaced "
        "by the evidence, store a superseding memory with remember. "
        "Deterministic entry point: the /why slash command. Distinct "
        "from `get_causal_chain` (entity-graph traversal over "
        "inferred relations) and `recall` (similarity retrieval): why "
        "replays RECORDED injection receipts only."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["receipt_ids"],
        "properties": {
            "receipt_ids": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1, "maximum": 2147483647},
                "minItems": 1,
                "maxItems": 999,
                "description": (
                    # source: ADR-0452
                    "Receipt ids from ⟦rcpt:N⟧ markers in the current context; at "
                    "most 999 per call. Pass markers present before the answer being "
                    "questioned, excluding the marker attached to the current prompt."
                ),
                "examples": [[412], [412, 415, 431]],
            },
        },
    },
}


# source: ADR-0452
_MAX_RECEIPT_IDS = 999
# source: ADR-0452
_INT4_MAX = 2_147_483_647


def _parse_receipt_ids(raw: Any) -> list[int]:
    """Coerce the argument into a deduplicated, ordered id list — loudly.

    source: ADR-0452"""
    if not isinstance(raw, list) or not raw:
        raise ValueError("receipt_ids requires a non-empty list of receipt ids")
    if len(raw) > _MAX_RECEIPT_IDS:
        raise ValueError(
            f"receipt_ids accepts at most {_MAX_RECEIPT_IDS} ids per call, "
            f"got {len(raw)}"
        )
    ids: list[int] = []
    seen: set[int] = set()
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"receipt_ids entries must be integers, got {value!r}")
        try:
            rid = int(value)
        except ValueError as exc:
            raise ValueError(
                f"receipt_ids entries must be integers, got {value!r}"
            ) from exc
        if rid < 1:
            raise ValueError(f"receipt ids are positive (SERIAL), got {rid}")
        if rid > _INT4_MAX:
            raise ValueError(f"receipt ids fit int4 (SERIAL), got {rid}")
        if rid not in seen:
            seen.add(rid)
            ids.append(rid)
    return ids


def _iso(value: Any) -> str | None:
    """ISO-8601 string for datetime-ish values; None passes through."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _evidence_item(row: dict[str, Any]) -> dict[str, Any]:
    """Map one store row to one evidence row (recorded facts only)."""
    item: dict[str, Any] = {
        "receipt_id": int(row["receipt_id"]),
        "channel": row["channel"],
        "session_id": row["session_id"],
        "emitted_at": _iso(row["emitted_at"]),
        "memory_id": int(row["memory_id"]),
        "rank": int(row["rank"]),
        "score": None if row["score"] is None else float(row["score"]),
        "memory_missing": row["memory_row_id"] is None,
    }
    if row["memory_row_id"] is not None:
        item["content"] = row["content"]
        item["superseded_by_id"] = row["superseded_by_id"]
        item["memory_created_at"] = _iso(row["memory_created_at"])
        item["memory_source"] = row["memory_source"]
        item["memory_domain"] = row["memory_domain"]
    return item


async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """Resolve receipt ids into bounded presence-in-context evidence."""
    receipt_ids = _parse_receipt_ids(args.get("receipt_ids"))
    store = get_shared_store()
    rows = store.fetch_injection_receipts(receipt_ids)
    evidence = [_evidence_item(r) for r in rows]
    resolved_ids = {e["receipt_id"] for e in evidence}
    resp: dict[str, Any] = {
        "evidence": evidence,
        "count": len(evidence),
        "receipts_resolved": sorted(resolved_ids),
        "receipts_unknown": [r for r in receipt_ids if r not in resolved_ids],
        "semantics": "presence-in-context",
    }
    # source: ADR-0452
    settings = get_memory_settings()
    resp = bound_payload(
        resp, [ListTarget("evidence", weight_key="score")], settings.MAX_RESPONSE_CHARS
    )
    resp["count"] = len(resp["evidence"])
    return resp
