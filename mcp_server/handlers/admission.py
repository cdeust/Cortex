"""Phase 5: admission control for MCP tool handlers.

Per-tool semaphore that bounds concurrency so one client cannot
exhaust the pool or the thread executor by hammering a single tool.

Tool calls go through ``run_admitted`` (``safe_handler``), which keeps the
slot until the worker thread ends, even when the caller is cancelled
(issue #728). ``admit`` holds a slot for the duration of a ``with`` block.

source: ADR-0329"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, TypeVar

from mcp_server.handlers import worker_ledger
from mcp_server.handlers.latency_class import DEFAULT_SEMAPHORE, classify

logger = logging.getLogger(__name__)

T = TypeVar("T")

# source: ADR-0329
_OVERRIDES: dict[str, int] = {
    # Higher budget: these tools are read-only / very cheap, safe to
    # run many in parallel.
    "recall": 8,
    "memory_stats": 8,
    "detect_domain": 8,
    "list_domains": 8,
    "query_methodology": 8,
    # Lower budget: mutations need slightly more care.
    "remember": 4,
}

# Process-local semaphore cache. asyncio.Semaphore is not thread-safe,
# but since admission runs on the main asyncio event loop there's only
# ever one of these per process.
_SEMS: dict[str, asyncio.Semaphore] = {}


def _budget_for(tool_name: str) -> int:
    if tool_name in _OVERRIDES:
        return _OVERRIDES[tool_name]
    cls = classify(tool_name)
    return DEFAULT_SEMAPHORE[cls]


def _get_semaphore(tool_name: str) -> asyncio.Semaphore:
    """Lazy-init per-tool semaphore on first use."""
    sem = _SEMS.get(tool_name)
    if sem is None:
        sem = asyncio.Semaphore(_budget_for(tool_name))
        _SEMS[tool_name] = sem
    return sem


@asynccontextmanager
async def admit(tool_name: str) -> AsyncIterator[None]:
    """Acquire the per-tool admission semaphore for the call duration.

    Blocks when the tool's concurrent-call budget is exhausted. No
    timeout — the admission semaphore is the backpressure signal; the
    pool handles DB-level timeout separately.

    Usage:
        async with admit("recall"):
            result = await do_work()
    """
    sem = _get_semaphore(tool_name)
    async with sem:
        yield


async def run_admitted(tool_name: str, func: Callable[..., T], *args: Any) -> T:
    """Run ``func(*args)`` on a worker thread inside the tool's admission budget.

    The slot is released when the worker finishes, not when the caller stops
    waiting: ``asyncio.to_thread`` cannot stop a running thread, so a cancelled
    caller that released its slot let a new request start a worker beyond the
    declared budget (issue #728: budget 4, four cancelled callers, a fifth
    request made five active workers). A worker whose caller was cancelled has
    its outcome logged and recorded in ``worker_ledger`` when it ends.

    source: issue #728"""
    sem = _get_semaphore(tool_name)
    await sem.acquire()
    worker = asyncio.ensure_future(asyncio.to_thread(func, *args))
    worker_ledger.worker_started(tool_name)
    run = _Run(tool_name, sem, worker)
    worker.add_done_callback(run.worker_done)
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        run.caller_cancelled()
        raise


@dataclass
class _Run:
    """One admitted worker: its slot, and whether its caller stopped waiting.

    Done callbacks run on the event loop after the worker ends, so the caller
    can be cancelled before (the worker runs on, abandoned) or after it (the
    result existed but never reached the caller). Both count as abandoned.

    source: issue #728"""

    tool_name: str
    sem: asyncio.Semaphore
    worker: asyncio.Future
    abandoned: bool = False
    ended: bool = False

    def worker_done(self, _worker: asyncio.Future) -> None:
        self.ended = True
        self.sem.release()
        outcome = _outcome(self.tool_name, self.worker) if self.abandoned else None
        worker_ledger.worker_ended(self.tool_name, outcome)

    def caller_cancelled(self) -> None:
        self.abandoned = True
        if self.ended:
            outcome = _outcome(self.tool_name, self.worker)
            worker_ledger.abandoned_after_end(self.tool_name, outcome)
        else:
            worker_ledger.caller_abandoned(self.tool_name)


def _outcome(tool_name: str, worker: asyncio.Future) -> str:
    """Name and log how a worker ended after its caller was cancelled.

    Reading ``exception()`` here is what retrieves it: no caller awaits it.

    source: issue #728"""
    if worker.cancelled():
        outcome, detail = "cancelled", "was cancelled"
    elif worker.exception() is not None:
        outcome, detail = "raised", f"raised {type(worker.exception()).__name__}"
    else:
        outcome, detail = "completed", "completed"
    logger.warning("%s worker %s after its caller was cancelled", tool_name, detail)
    return outcome


def current_budget(tool_name: str) -> int:
    """Return the declared budget for a tool. For tests + observability."""
    return _budget_for(tool_name)


def reset_semaphores() -> None:
    """Drop all cached semaphores. For tests only — next admit() call
    re-initializes from the current budget table."""
    _SEMS.clear()
