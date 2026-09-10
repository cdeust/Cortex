"""Per-upstream-server admission governor — bounds concurrent in-flight
calls to a single upstream MCP child process.

source: ADR-0621"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import AsyncIterator

# source: ADR-0621
_DEFAULT_MAX_CONCURRENT_CALLS = 1

# source: ADR-0621
_WAIT_EXECUTOR_MAX_WORKERS = 8
_wait_executor = ThreadPoolExecutor(
    max_workers=_WAIT_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="upstream-governor-wait",
)

# source: ADR-0621
_SEMS: dict[str, threading.Semaphore] = {}
_BUDGETS: dict[str, int] = {}
_registry_lock = threading.Lock()


def _get_semaphore(server_name: str, max_concurrent: int) -> threading.Semaphore:
    """Lazy-init the per-server semaphore on first use.

    source: ADR-0621"""
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
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_wait_executor, sem.acquire)
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
