---
created: 2026-11-07T12:00:00Z
kind: adr
number: 1125
status: accepted
tags: [admission, cancellation, mcp, issue-728, amends-adr-0329]
title: A cancelled tool call's worker runs to completion inside its admission slot
---
# ADR-1125: A cancelled tool call's worker runs to completion inside its admission slot

## Status

accepted. Records the cancellation semantics that #885, #903, #902, #936 and #943 put on main for issue #728. Amends ADR-0329 (per-tool admission): a slot is owned by the worker, not by the caller.

## Context

Issue #728, first acceptance item: "Keep work counted until completion or a documented cooperative cancellation boundary." The issue's probe showed the gap: `safe_handler` released the admission slot when the awaiting task was cancelled, while the thread started by `asyncio.to_thread` kept running, so a budget of 4 reached 5 active workers.

What main does since those slices (read on main at a5764f6):

- `safe_handler` (`mcp_server/tool_error_handler.py`) runs every named tool through `run_admitted` (`mcp_server/handlers/admission.py`). The handler's coroutine runs on a fresh event loop in a worker thread (`_run_coroutine_on_thread`, ADR-0691).
- `run_admitted` acquires the slot, starts the worker, and releases the slot from the worker's done callback. The caller awaits the worker through `asyncio.shield`, so cancelling the caller does not cancel the worker.
- On cancellation the caller records the worker in `abandoned_work` (`in_flight`), and the worker's end is recorded as `completed`, `raised` or `cancelled`. `memory_stats` returns that registry as `abandoned_workers`.
- Nothing forwards the caller's cancellation into the worker: no handler receives a cancellation token, and the worker's event loop is not the server's loop.

## Decision

1. Cortex has no cooperative cancellation boundary. Once admitted, a named tool's handler runs to its end, whether its caller is still waiting or not. A `notifications/cancelled` from the client, or a disconnect, ends the caller only.
2. The admission slot belongs to the worker. It is released when the worker ends, never when the caller stops waiting, so the number of running workers of a tool never exceeds its declared budget (ADR-0329).
3. Work finished after abandonment is reported, not hidden: `memory_stats.abandoned_workers` gives, per tool, the abandoned workers still running and how the ended ones ended, since the server process started. A mutating tool's write lands (or fails) after the client stopped listening; the client learns it only through `memory_stats` or by reading the store.
4. A handler that wants to stop early must amend this ADR. The amendment has to name the point in the handler where stopping leaves the store consistent, say how the cancellation reaches the worker thread, keep the slot until the worker actually returns, and record that outcome in `abandoned_work`.
5. Out of scope: `safe_handler` called without `tool_name` (compatibility path) runs without admission, so its abandoned workers are neither bounded nor counted.

## Consequences

Positive: the declared concurrency budget holds under cancellation; a cancelled `remember` is not half-applied by an interruption inside the handler; the outcome of abandoned work is observable.

Negative: a cancelled long call keeps its thread and its slot until it ends, so new calls of that tool wait behind it. A client that cancels to free capacity frees nothing.

Tests: `tests_py/handlers/test_admission_cancellation.py` and `tests_py/server/test_safe_handler_cancellation.py` (the slot is kept until the worker ends; the issue's budget-4 probe), `tests_py/handlers/test_abandoned_work_status.py` and `tests_py/handlers/test_memory_stats_mapping.py` (outcomes and their report), `tests_py/server/test_mcp_protocol_cancellation.py` and `tests_py/server/test_mcp_protocol_cancellation_remember.py` (real MCP `notifications/cancelled` and client disconnect, the second with the real `remember` on an isolated Cortex store).
