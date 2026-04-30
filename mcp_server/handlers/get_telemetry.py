"""Handler: get_telemetry — return in-process telemetry counters.

Surfaces the read/write workload distribution captured by
``mcp_server.core.telemetry``: per-op call count, latency
(sum/avg/max), byte volume, success/failure split, and the computed
read/write ratio. This grounds the paper's "100x more reads than
writes" claim in measurement (Popper C6).

Composition root: pure-logic call into core; no I/O beyond what
``telemetry.summary()`` already does (memory snapshot + log path).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import telemetry
from mcp_server.handlers._tool_meta import READ_ONLY

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
        },
    },
    "description": (
        "Return the in-process telemetry snapshot: per-op call counts, "
        "latency, byte volume, success/failure split, and the computed "
        "read/write ratio. Use this to verify Cortex's empirical "
        "read/write workload distribution (Popper C6 — grounds the "
        "paper's '100x more reads than writes' claim in measurement, "
        "not assertion). Counters are per-process and reset on restart; "
        "the durable record is the JSONL at "
        "~/.claude/methodology/telemetry.jsonl."
    ),
    "inputSchema": {"type": "object", "properties": {}},
}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return current telemetry summary.

    precondition: none (read-only over in-memory dict).
    postcondition: returns ``telemetry.summary()`` verbatim.
    """
    return telemetry.summary()
