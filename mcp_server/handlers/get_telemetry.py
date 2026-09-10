"""Handler: get_telemetry — return in-process telemetry counters.

Composition root: pure-logic call into core; no I/O beyond what
``telemetry.summary()`` already does (memory snapshot + log path).

source: ADR-0397"""

from __future__ import annotations

from typing import Any

from mcp_server.core import telemetry
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.embedding_engine import current_embedding_mode

schema = {
    "title": "Get Telemetry (read/write counters)",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["counters", "ratio_reads_writes"],
        "properties": {
            "counters": {
                "type": "object",
                "description": (
                    "Per-op counter map. Key is the canonical op name "
                    "(recall, remember, forget, ...); value is "
                    "{count, ok, fail, bytes_in, bytes_out, "
                    "result_count, latency_ms_sum, latency_ms_max}."
                ),
            },
            "derived": {
                "type": "object",
                "description": (
                    "Per-op derived stats: avg_latency_ms, max_latency_ms."
                ),
            },
            "ratio_reads_writes": {
                "type": "number",
                "description": (
                    "reads / max(writes, 1). Reads = recall, "
                    "recall_hierarchical, navigate_memory, "
                    "get_causal_chain, drill_down. Writes = remember, "
                    "forget, validate_memory, rate_memory."
                ),
            },
            "log_path": {
                "type": "string",
                "description": "Absolute path to the JSONL audit log.",
            },
            "disabled": {
                "type": "boolean",
                "description": (
                    "True if CORTEX_TELEMETRY_DISABLED=1 was set in the "
                    "environment when the process started."
                ),
            },
            "embedding_mode": {
                "type": "string",
                "description": (
                    # source: ADR-0397
                    "Embedding provenance for this process: 'neural' = "
                    "sentence-transformers, 'fallback' = download-free algorithmic "
                    "embeddings (lower fidelity, engaged when the model is absent), "
                    "'unknown' = no encode has run yet. Fallback and neural vectors "
                    "never cross-rank."
                ),
            },
        },
    },
    "description": (
        # source: ADR-0397
        "Return the in-process telemetry snapshot: per-operation call "
        "counts, latency, byte volume, success/failure split, and "
        "computed read/write ratio. Counters reset on process restart; "
        "the durable record is the JSONL at "
        "~/.claude/methodology/telemetry.jsonl."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return current telemetry summary.

    precondition: none (read-only over in-memory dict).
    postcondition: returns ``telemetry.summary()`` augmented with
    ``embedding_mode`` so a caller can tell whether semantic recall
    is running on neural or download-free fallback embeddings.

    source: ADR-0397"""
    summary = telemetry.summary()
    summary["embedding_mode"] = current_embedding_mode()
    return summary
