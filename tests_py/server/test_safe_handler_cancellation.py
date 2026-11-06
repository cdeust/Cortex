"""Issue #728 through ``safe_handler``: the probe of the issue, as a test.

Budget 4 (an interactive tool with no override), four callers cancelled while
their handlers run, then a fifth request. Before the fix the fifth handler ran
beside the four abandoned ones: five active workers for a budget of four.

Orderings are driven by ``threading.Event``, never by elapsed time.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from mcp_server.handlers.admission import (
    _get_semaphore,
    current_budget,
    reset_semaphores,
)
from mcp_server.observability import metrics
from mcp_server.tool_error_handler import safe_handler

# source: mcp_server/handlers/latency_class.py — an interactive tool with no
# override in admission._OVERRIDES has the class default budget of 4.
_TOOL = "detect_gaps"
# source: deadlock guard, not a measurement — a wait that a correct
# implementation satisfies at once, bounded so a broken one fails the test.
_GUARD = 5.0


@pytest.fixture(autouse=True)
def _clean_state():
    reset_semaphores()
    metrics.reset()
    yield
    reset_semaphores()
    metrics.reset()


class _Handlers:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.started = threading.Semaphore(0)
        self.release = threading.Event()

    async def blocking(self, args: dict) -> dict:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.started.release()
        self.release.wait(_GUARD)
        with self._lock:
            self.active -= 1
        return {"n": args["n"]}


@pytest.mark.asyncio
async def test_cancelled_callers_cannot_push_workers_past_the_budget():
    budget = current_budget(_TOOL)
    assert budget == 4
    handlers = _Handlers()
    try:
        callers = [
            asyncio.ensure_future(safe_handler(handlers.blocking, {"n": i}, _TOOL))
            for i in range(budget)
        ]
        for _ in range(budget):
            assert await asyncio.to_thread(handlers.started.acquire, True, _GUARD)
        for caller in callers:
            caller.cancel()
        await asyncio.gather(*callers, return_exceptions=True)
        # The four abandoned workers still hold the whole budget.
        assert _get_semaphore(_TOOL).locked()

        fifth = asyncio.ensure_future(safe_handler(handlers.blocking, {"n": 5}, _TOOL))
        for _ in range(5):
            await asyncio.sleep(0)
        assert handlers.active == budget
        assert not fifth.done()

        handlers.release.set()
        assert await asyncio.wait_for(fifth, _GUARD) == {"n": 5}
        assert handlers.peak == budget
    finally:
        handlers.release.set()


@pytest.mark.asyncio
async def test_duration_is_recorded_for_a_caller_that_waits():
    async def handler(args: dict) -> dict:
        return {"ok": True}

    result = await asyncio.wait_for(safe_handler(handler, {}, _TOOL), _GUARD)
    assert result == {"ok": True}
    out = metrics.render()
    assert 'cortex_tool_duration_seconds_count{tool="detect_gaps"} 1' in out
    assert 'cortex_tool_calls_total{status="ok",tool="detect_gaps"} 1' in out
