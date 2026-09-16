"""Handler: predict — record what is expected to happen, before it happens.

Cortex stores what happened; without this it cannot be wrong in a way it
notices. A prediction is written open, carrying the confidence its author
held at the time, and stays that way until an observation settles it
through `resolve_prediction` (issue #597).

source: ADR-1076"""

from __future__ import annotations

from typing import Any

from mcp_server.handlers._tool_meta import NON_IDEMPOTENT_WRITE
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.prediction_store import insert_prediction

schema = {
    "annotations": NON_IDEMPOTENT_WRITE,
    "description": (
        "Record a falsifiable prediction before its outcome is known: the "
        "claim it belongs to, what is expected to happen, the test that "
        "would settle it, and the confidence held right now (0 to 1). The "
        "row stays open until `resolve_prediction` settles it against an "
        "observation, and `calibration` then scores the confidence against "
        "what actually happened. Write the prediction BEFORE running the "
        "test: a confidence stated afterwards measures nothing. Distinct "
        "from `remember` (stores what happened, not what is expected) and "
        "from `ingest_findings` (consumes another tool's findings run). "
        "Mutates the predictions table. Returns {prediction_id, status}."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["claim", "prediction", "test", "confidence"],
        "properties": {
            "claim": {
                "type": "string",
                "description": (
                    "The explanation or belief this prediction puts at risk."
                ),
                "examples": ["the timeout comes from connection-pool exhaustion"],
            },
            "prediction": {
                "type": "string",
                "description": (
                    "What is expected to happen, in terms an observation can "
                    "contradict."
                ),
                "examples": ["raising concurrency raises the failure rate"],
            },
            "test": {
                "type": "string",
                "description": "The observation or experiment that would settle it.",
                "examples": ["run the load test at twice the concurrency"],
            },
            "confidence": {
                "type": "number",
                "description": (
                    "How likely the author thinks the prediction is to hold, "
                    "0 to 1. A constant 0.5 scores 0.25, the point where a "
                    "forecast carries no information."
                ),
                "minimum": 0.0,
                "maximum": 1.0,
                "examples": [0.7, 0.35],
            },
            "domain": {
                "type": "string",
                "description": "Cognitive domain; omit to leave unscoped.",
            },
            "directory": {
                "type": "string",
                "description": "Absolute project directory this belongs to.",
            },
            "memory_id": {
                "type": "integer",
                "description": "Memory this prediction is about, when there is one.",
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    missing = [
        field
        for field in ("claim", "prediction", "test")
        if not (args.get(field) or "").strip()
    ]
    if missing:
        return {"error": f"empty or missing: {', '.join(missing)}"}
    confidence = args.get("confidence")
    if confidence is None or not 0.0 <= float(confidence) <= 1.0:
        return {"error": "confidence must be a number between 0 and 1"}

    store = _get_store()
    prediction_id = insert_prediction(
        store._conn,
        {
            "claim": args["claim"].strip(),
            "prediction": args["prediction"].strip(),
            "test": args["test"].strip(),
            "confidence": float(confidence),
            "domain": args.get("domain") or "",
            "directory": args.get("directory") or "",
            "memory_id": args.get("memory_id"),
        },
    )
    return {"prediction_id": prediction_id, "status": "open"}
