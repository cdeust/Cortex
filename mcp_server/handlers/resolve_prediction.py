"""Handler: resolve_prediction — settle an open prediction against evidence.

The caller supplies the verdict, what was observed, the kind of source that
settled it and a reference to that source. Cortex never fetches the
evidence and knows nothing about any particular host, review convention or
repository layout, which is what makes the contract usable wherever Cortex
runs rather than only where this project's own conventions do (issue #597).

A resolution without a reference is refused, the same discipline the
project applies to any claim.

source: ADR-1076"""

from __future__ import annotations

from typing import Any

from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.prediction_store import (
    SOURCE_KINDS,
    VERDICTS,
    get_prediction,
    resolve_prediction,
)

schema = {
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Settle an open prediction: what was observed, the verdict "
        "(confirmed, refuted, or abandoned when the test was never run), "
        "the kind of source that settled it (review, ci, test, manual) and "
        "a reference to that source, such as a review-comment URL or a CI "
        "run id. Cortex does not fetch the evidence and knows nothing about "
        "your host or repository: the caller maps its own convention onto "
        "these fields, so the same contract works in any repository. A "
        "resolution carrying no reference is refused, and a prediction "
        "resolves once. `calibration` scores the resolved rows. Mutates the "
        "predictions table. Returns {prediction_id, verdict, resolved}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [
            "prediction_id",
            "verdict",
            "observed",
            "source_kind",
            "source_ref",
        ],
        "properties": {
            "prediction_id": {
                "type": "integer",
                "description": "The open prediction to settle, from `predict`.",
            },
            "verdict": {
                "type": "string",
                "enum": list(VERDICTS),
                "description": (
                    "confirmed or refuted score the author's confidence; "
                    "abandoned records that the test was never run and "
                    "scores nothing."
                ),
            },
            "observed": {
                "type": "string",
                "description": "What actually happened, in the terms the test set.",
            },
            "source_kind": {
                "type": "string",
                "enum": list(SOURCE_KINDS),
                "description": "What settled it.",
            },
            "source_ref": {
                "type": "string",
                "description": (
                    "Where that evidence lives: a URL, a run id, a commit, "
                    "anything a reader can follow."
                ),
                "examples": ["https://github.com/owner/repo/pull/12#issuecomment-345"],
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _refusal(args: dict[str, Any]) -> str | None:
    """Why this resolution cannot be recorded, or None when it can."""
    if args.get("prediction_id") is None:
        return "prediction_id required"
    if args.get("verdict") not in VERDICTS:
        return f"verdict must be one of: {', '.join(VERDICTS)}"
    if args.get("source_kind") not in SOURCE_KINDS:
        return f"source_kind must be one of: {', '.join(SOURCE_KINDS)}"
    if not (args.get("source_ref") or "").strip():
        return "source_ref required: a resolution names the evidence that settled it"
    if not (args.get("observed") or "").strip():
        return "observed required: say what actually happened"
    return None


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    refusal = _refusal(args)
    if refusal is not None:
        return {"error": refusal, "resolved": False}

    store = _get_store()
    prediction_id = int(args["prediction_id"])
    if get_prediction(store._conn, prediction_id) is None:
        return {"error": f"prediction {prediction_id} not found", "resolved": False}

    settled = resolve_prediction(
        store._conn,
        prediction_id,
        verdict=args["verdict"],
        observed=args["observed"].strip(),
        source_kind=args["source_kind"],
        source_ref=args["source_ref"].strip(),
    )
    if not settled:
        return {
            "error": f"prediction {prediction_id} is already resolved",
            "prediction_id": prediction_id,
            "resolved": False,
        }
    return {
        "prediction_id": prediction_id,
        "verdict": args["verdict"],
        "resolved": True,
    }
