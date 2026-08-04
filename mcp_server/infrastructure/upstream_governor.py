"""Per-upstream-server admission governor — bounds concurrent in-flight
calls to a single upstream MCP child process.

Why
---
Upstream MCP servers (e.g. the ``ai-architect-mcp-codebase`` Rust binary behind
the ``codebase`` server) are **single OS processes**. Two Cortex handlers
that each pass admission under *different* per-tool semaphores
(``ingest_codebase`` and ``codebase_analyze`` are distinct names, each
``Semaphore(1)`` — see handlers/admission.py) can still issue heavy
``query_graph`` / ``analyze_codebase`` calls to the **same** child at the
same time. Back-to-back heavy graph queries with no breathing room drive
the child's RSS up until the OS kills it; the next stdin write then raises
``ConnectionResetError: Connection lost``. source: ingest_codebase
ConnectionResetError RCA 2026-06-09.

This governor serialises (or bounds) calls **per upstream server name**,
across every Cortex handler, so the shared child is never asked to serve
more concurrent work than it can hold.

Design
------
* Keyed by upstream server name, NOT by tool — the constraint is the child
  process, which is shared across tools.
* Backed by ``threading.Semaphore``, NOT ``asyncio.Semaphore``: batch
  handlers run their coroutine on a fresh per-call event loop in a worker
  thread (tool_error_handler._run_coroutine_on_thread), so an asyncio
  primitive created on one loop and awaited on another raises
  "bound to a different event loop". A threading.Semaphore is loop-agnostic
  and process-global; the blocking acquire is offloaded via
  ``asyncio.to_thread`` so the calling loop stays responsive.
* Default permit count is 1 — full serialisation of the single-process
  child, mirroring admission's batch-class ``Semaphore(1)`` (a single heavy
  writer at a time). Override per server in mcp-connections.json via
  ``maxConcurrentCalls``. source: Kleinrock (1975) bounded-buffer M/M/c/K —
  c is a property of the served resource (here, one process).
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import AsyncIterator

# Permits per upstream server when the config does not specify
# ``maxConcurrentCalls``. 1 = serialise (the conservative default for a
# single-process child). source: admission.py batch class Semaphore(1).
_DEFAULT_MAX_CONCURRENT_CALLS = 1

# Process-global registry. ``threading.Semaphore`` is thread-safe and
# loop-agnostic, so one instance per server name is shared correctly across
# the worker-thread event loops that batch handlers run on. The dict itself
# is guarded by ``_registry_lock`` for first-use creation.
_SEMS: dict[str, threading.Semaphore] = {}
_BUDGETS: dict[str, int] = {}
_registry_lock = threading.Lock()


def _get_semaphore(server_name: str, max_concurrent: int) -> threading.Semaphore:
    """Lazy-init the per-server semaphore on first use.

    The first caller's ``max_concurrent`` fixes the budget; later callers
    reuse it (the budget is a property of the served child, not the call).
    """
    sem = _SEMS.get(server_name)
    if sem is None:
        with _registry_lock:
            sem = _SEMS.get(server_name)
            if sem is None:
                budget = max(1, max_concurrent)
                sem = threading.Semaphore(budget)
                _SEMS[server_name] = sem
                _BUDGETS[server_name] = budget
    return sem


@asynccontextmanager
async def govern(
    server_name: str,
    max_concurrent: int = _DEFAULT_MAX_CONCURRENT_CALLS,
) -> AsyncIterator[None]:
    """Hold the per-server admission permit for one upstream call.

    Blocks (off the event loop) when the server's concurrent-call budget is
    exhausted, applying backpressure to the caller. No timeout — the permit
    is the backpressure signal; the MCP client handles per-call timeout
    separately.

    Usage:
        async with govern("codebase", max_concurrent=1):
            result = await client.call("query_graph", args)
    """
    sem = _get_semaphore(server_name, max_concurrent)
    await asyncio.to_thread(sem.acquire)
    try:
        yield
    finally:
        sem.release()


def current_budget(server_name: str) -> int:
    """Return the declared permit count for a server. Tests + observability."""
    return _BUDGETS.get(server_name, _DEFAULT_MAX_CONCURRENT_CALLS)


def reset() -> None:
    """Drop all cached semaphores. For tests only — next govern() call
    re-initialises from the current budget."""
    with _registry_lock:
        _SEMS.clear()
        _BUDGETS.clear()
