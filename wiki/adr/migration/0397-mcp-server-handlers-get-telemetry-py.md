# ADR-0397: mcp_server/handlers/get_telemetry.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/get_telemetry.py`; original SHA-256 `a748a8b31efd1374b88409d747fc74fc444a2791093a3b515d9ca979af89db34`.

## Original docstring, lines 1–11

````text
"""Handler: get_telemetry — return in-process telemetry counters.

Surfaces the read/write workload distribution captured by
``mcp_server.core.telemetry``: per-op call count, latency
(sum/avg/max), byte volume, success/failure split, and the computed
read/write ratio. This grounds the paper's "100x more reads than
writes" claim in measurement (Popper C6).

Composition root: pure-logic call into core; no I/O beyond what
``telemetry.summary()`` already does (memory snapshot + log path).
"""
````

## Reviewed remaining docstring (mcp_server/handlers/get_telemetry.py, interim lines 85–91)

````text
Return current telemetry summary.

precondition: none (read-only over in-memory dict).
postcondition: returns ``telemetry.summary()`` augmented with
``embedding_mode`` (issue #169) so a caller can tell whether semantic recall
is running on neural or download-free fallback embeddings.
````

## Original schema description, interim lines 71–78

````text
Return the in-process telemetry snapshot: per-op call counts, latency, byte volume, success/failure split, and the computed read/write ratio. Use this to verify Cortex's empirical read/write workload distribution (Popper C6 — grounds the paper's '100x more reads than writes' claim in measurement, not assertion). Counters are per-process and reset on restart; the durable record is the JSONL at ~/.claude/methodology/telemetry.jsonl.
````

## Original schema description, interim lines 61–65

````text
Embedding provenance for this process (issue #169): 'neural' = sentence-transformers, 'fallback' = download-free algorithmic embeddings (lower fidelity, engaged when the model is absent), 'unknown' = no encode has run yet. Fallback and neural vectors never cross-rank.
````

