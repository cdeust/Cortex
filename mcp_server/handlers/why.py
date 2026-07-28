"""Handler: why -- resolve injection receipts into presence evidence.

Blame path T3 (decision Cortex 4255039): the receipt-based primary
path. The model reads the ⟦rcpt:id⟧ markers present in its own context
(correction 2 — server-side session-temporal resolution does not exist
in MCP) and hands the ids back here; this handler resolves them against
the append-only receipt trail into presence-in-context evidence: which
memories each channel put in front of the model, when, at which
persisted rank and score.

Locked lexicon: this is evidence of PRESENCE IN CONTEXT — Pearl's
ladder rung 1, recorded associations only — never a causal claim about
what produced an answer.

Anti-self-pollution (correction 4): the receipt injected alongside the
CURRENT prompt (its auto_recall block) must not enter the blame. Only
the model can identify that marker — it is the one attached to the
prompt asking the question — so the exclusion is enforced at the
instruction layer (this schema + the /why command); the response keeps
it auditable by carrying channel + emitted_at on every row.

Anti-flooding bound (correction 5): the response passes through
``bound_payload`` — the same measured budget as recall — so a long
session's receipts cannot drown the context; truncated rows keep their
ids for fetch-by-id.
"""

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
                                "Transcript-derived session identity; null for "
                                "receipts emitted by the MCP recall handler "
                                "(no session in scope, decision 4255039 "
                                "correction 1)."
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
                                "True when the memory row no longer exists "
                                "(hard-forget after injection). The receipt "
                                "remains valid presence evidence — that is "
                                "why receipt items carry no FK."
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
                    "Locked lexicon (decision 4255039): this response proves "
                    "what was PRESENT in the context, never what CAUSED an "
                    "answer (Pearl's ladder, rung 1)."
                ),
            },
        },
    },
    "description": (
        "Blame path resolver (decision 4255039): turn the ⟦rcpt:N⟧ markers "
        "visible in the current context into presence-in-context evidence — "
        "which memories each injection channel (recall, session_start, "
        "auto_recall, agent_briefing) put into the context, when, at which "
        "persisted rank and score. This is evidence of PRESENCE, never "
        "causality. Protocol: collect the ⟦rcpt:N⟧ markers that were in "
        "context BEFORE the answer being questioned; EXCLUDE the marker "
        "injected alongside the current prompt's own memory block "
        "(self-pollution guard) — then pass the ids here. To correct a wrong "
        "memory surfaced by the evidence, store a superseding memory with "
        "remember. Deterministic entry point: the /why slash command. "
        "Distinct from `get_causal_chain` (entity-graph traversal over "
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
                    "Receipt ids read from ⟦rcpt:N⟧ markers in the current "
                    "context (at most 999 per call — bounded envelope, "
                    "ADR-0045 R2). Pass the markers present before the "
                    "answer being questioned; exclude the one attached to "
                    "the current prompt (decision 4255039 correction 4)."
                ),
                "examples": [[412], [412, 415, 431]],
            },
        },
    },
}


# Bounded envelope on the id list (ADR-0045 R2). 999 is the lowest
# documented hard limit on the fetch path: SQLite's default
# SQLITE_MAX_VARIABLE_NUMBER (sqlite.org/limits.html §9, releases before
# 3.32.0) and the SQLite fallback binds one parameter per id. It also
# keeps a worst-case all-unknown response (~7 JSON chars/id) far under
# MAX_RESPONSE_CHARS, which bound_payload cannot shrink (non-ListTarget).
_MAX_RECEIPT_IDS = 999
# Receipt ids are int4 (SERIAL); the PG path casts ::int[], so a larger
# value is unrepresentable — reject it instead of leaking a backend-
# specific NumericValueOutOfRange (PG) vs silent-unknown (SQLite) split.
_INT4_MAX = 2_147_483_647


def _parse_receipt_ids(raw: Any) -> list[int]:
    """Coerce the argument into a deduplicated, ordered id list — loudly.

    A malformed id list is a caller bug, not a degradation mode: raise
    with the exact offender instead of silently dropping it. bool is
    rejected explicitly (it is an int subclass and ``True`` would
    silently resolve receipt 1).
    """
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
    # Anti-flooding bound (correction 5): same measured budget as recall;
    # water-filling keeps the highest-scored rows fullest and every
    # truncated row keeps its memory_id for fetch-by-id.
    settings = get_memory_settings()
    resp = bound_payload(
        resp, [ListTarget("evidence", weight_key="score")], settings.MAX_RESPONSE_CHARS
    )
    resp["count"] = len(resp["evidence"])
    return resp
