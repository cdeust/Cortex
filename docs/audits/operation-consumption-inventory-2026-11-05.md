# Operation consumption: what Cortex attributes today (2026-11-05)

Issue #733, slice 1: before propagating an operation identity or recording new
units, list what the current telemetry measures, which work it attributes to a
user operation, and where an unknown value is reported as a number. This
document changes no behaviour. Every row cites the code read at `main` `149b943`;
the one runtime probe is reproduced below.

## The sample

One telemetry sample (`TelemetrySample`, `mcp_server/core/telemetry.py`) carries
`ts`, `op`, `latency_ms`, `bytes_in`, `bytes_out`, `result_count`, `ok`,
`skipped`, `tier` and `reranked_count`. It goes to the in-process counters
returned by `get_telemetry`, to the local JSONL `telemetry.jsonl`, and, only when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set, to the OTLP exporter
(`mcp_server/infrastructure/otel_exporter.py`, three instruments: duration, calls,
result count).

| Unit | Measured how | Source |
| --- | --- | --- |
| Wall time | `time.perf_counter()` around the handler or hook, or `time.monotonic()` in the capture worker | `handlers/_telemetry_wrap.py`, `hooks/_telemetry.py`, `hooks/capture_store.py` |
| Bytes in | UTF-8 length of `json.dumps(args)`; 0 for hooks and capture | `handlers/_telemetry_wrap.py::_safe_json_len` |
| Bytes out | UTF-8 text content of the MCP response, rewritten by the middleware from the SDK result; bytes written to stdout for hooks | `telemetry_middleware.py`, `hooks/_telemetry.py` |
| Retrieval work | route actually executed (`tier`) and passages the reranker scored (`reranked_count`) | `shared/telemetry_context.py` (ADR-0668) |
| Outcome | ok, skipped (declined) or error, counted apart | `core/telemetry.py::record` (issue #660) |
| Embedding mode | `neural`, `fallback` or `unknown`, **per process**, added by `get_telemetry` only, not per sample | `handlers/get_telemetry.py` |

Not measured anywhere in `mcp_server/`: CPU time (no `process_time`,
`thread_time` or `getrusage` call), memory per operation, storage bytes written,
embedding or reranker inference time as its own unit, and provider tokens.

## Which operations emit a sample

| Emitter | Operations (`op`) | Source |
| --- | --- | --- |
| MCP handler wrapper `instrument` | `recall`, `recall_hierarchical`, `remember`, `forget`, `validate_memory`, `rate_memory`, `navigate_memory`, `get_causal_chain`, `drill_down`, `query_methodology` (10 tools at the audit); `consolidate` since #733 slice 3 | the `instrument(...)` line of each handler |
| `remember_bulk` | one `remember` sample per item, no sample for the bulk call | `handlers/remember_bulk.py` |
| Hooks `observe_hook` | `session_start`, `auto_recall` | `hooks/session_start.py`, `hooks/auto_recall.py` |
| Capture worker | `capture_processed` on success; `capture_skipped`, `capture_spool_stalled`, `capture_worker_lifecycle` on failure | `hooks/capture_store.py`, `hooks/capture_dispatch.py`, `hooks/capture_worker.py` |

`TelemetryMiddleware` creates no sample: it defers and finalizes the samples the
handlers above already recorded. Every other registered tool, `consolidate`
included, records nothing, so its wall time, bytes and outcome are absent from
`get_telemetry` and the JSONL (static reading: no `instrument` or
`telemetry.record` call in those handlers). `consolidate` records one sample per
call since #733 slice 3.

## Attribution to a user operation

The acceptance asks for one identity across foreground work, retries and
background or derived processing. Today:

- **No operation identity.** No sample carries an operation, request, session
  or trace identifier (no such field in `TelemetrySample`; no `operation_id`,
  `request_id` or `trace_id` in `mcp_server/`). Samples are joined only by `op`
  and `ts`.
- **Nested work is a separate, unlinked sample.** The middleware updates only
  the sample whose `op` equals the called tool name; a handler called inside
  another keeps its own sample with nothing pointing to the caller
  (`telemetry_middleware.py::_finalize_response`).
- **Background capture is unlinked.** A captured tool event is processed by
  the resident worker, which records `capture_processed` with its own wall time;
  `origin_tool` is logged, not stored in the sample (`hooks/capture_store.py`).
- **Retries are not counted.** No sample field records a retry or attempt.
- **Derived work inside a tool is folded into its wall time.** The HTTP `HEAD`
  checks of `validate_memory` (`urllib.request`, `handlers/validate_memory.py`)
  and the embedding and reranker inference of `recall` are included in that
  tool's `latency_ms`, with no breakdown (#722 owns the recall breakdown).

## Engine, host model and optional integrations

- **Engine:** the samples above. The host model's own consumption (the Claude
  or Codex session that calls the tools) is not visible to Cortex and is not
  recorded; nothing in a sample separates it.
- **Optional provider: headless authoring.** `consolidate` runs
  `run_wiki_maintenance`, which, when headless authoring is enabled, runs
  `claude --print --output-format json` per wiki gap
  (`handlers/consolidation/claude_invoke.py`). The only usage read is
  `total_cost_usd`, a client-side estimate. It is summed into
  `CycleSummary.usd_spent` and returned in the `consolidate` response under
  `headless_authoring`; it is not a telemetry sample, and no token, cache or
  reasoning count is read from the CLI output.
- **Unknown cost is reported as 0.0.** `_parse_invoke_response` returns
  `cost_usd=0.0` when the CLI exits non-zero, prints nothing, prints non-JSON,
  or omits `total_cost_usd`; `InvokeResult` documents "0.0 when unavailable".
  A cycle whose calls all failed to report a cost therefore shows
  `usd_spent: 0.0`, indistinguishable from a free cycle. This is the explicit
  unknown the acceptance requires and the current code does not have.
- **Optional OTLP export** mirrors the same samples; it adds no unit.

Probe (this container, `main` `149b943`, Python 3.11, no `claude` call made):

```python
from mcp_server.handlers.consolidation import headless_authoring as root
from mcp_server.handlers.consolidation.claude_invoke import _parse_invoke_response as p

p(1, b"", b"", root)  # InvokeResult(text=None, cost_usd=0.0)
p(0, b"", b"", root)  # InvokeResult(text=None, cost_usd=0.0)
p(0, b"not json", b"", root)  # InvokeResult(text='not json', cost_usd=0.0)
p(0, b'{"result":"x"}', b"", root)  # InvokeResult(text='x', cost_usd=0.0)
p(0, b'{"result":"x","total_cost_usd":0.0123}', b"", root)  # cost_usd=0.0123
```

## Remaining slices of #733

1. Report an unknown provider cost as unknown (`None`), not `0.0`, through
   `InvokeResult`, `CycleBudget` and the `consolidate` response.
2. Give each MCP call and each hook invocation an operation identity carried by
   every nested sample and handed to the capture worker and background cycles.
   Delivered: one id per MCP call (`core/telemetry.py::capture_records`), and
   one id per captured payload stored by the resident worker or the spool
   drainer (`begin_operation`, called by `hooks/capture_store.py::remember` and
   `hooks/capture_drain.py::drain_pending`). Not delivered: an id for a hook
   invocation, and its hand-off to the worker. The capture payload has a fixed
   key set (`capture_worker_policy.validate_payload`) and no version, and a
   resident worker started before an upgrade keeps running the old code: it
   would refuse a payload that carries a new key. Background cycles
   (`consolidate`) carry no id either.
3. Record CPU time beside wall time, and emit samples for the tools that record
   none today, starting with `consolidate`. Delivered: `consolidate` is wrapped by
   `instrument` (`handlers/consolidate.py`), one sample per call, with the
   operation id of the MCP call; a run started by a session hook records its
   sample with no id. Not delivered: CPU time (an async call shares the process
   with other calls and hands work to threads, so `process_time` around it is not
   attributable to it), and samples for the other tools that record none.
4. Read the provider usage the CLI reports, beyond `total_cost_usd`, with its
   provenance, after checking the fields against the CLI version in use.

Not verified here: the PostgreSQL paths (no PostgreSQL in this container) and
any live `claude -p` output; the rows above are read from the code.
