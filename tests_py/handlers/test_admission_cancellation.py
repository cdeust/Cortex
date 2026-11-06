"""Issue #728: a cancelled caller keeps its admission slot until its worker ends.

``asyncio.to_thread`` cannot stop a running thread. Before the fix, cancelling
the awaiting task left ``admit`` and released the slot while the worker kept
running, so a new request started one worker more than the declared budget.

Every ordering here is driven by ``threading.Event``. ``_GUARD`` only bounds a
wait that a broken implementation would never satisfy, so such a run fails
instead of hanging; no verdict depends on elapsed time.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from mcp_server.handlers.admission import (
    _get_semaphore,
    current_budget,
    reset_semaphores,
    run_admitted,
)

# source: mcp_server/handlers/latency_class.py — consolidate is a batch tool,
# budget 1, so one held slot is the whole budget.
_TOOL = "consolidate"
_LOGGER = "mcp_server.handlers.admission"
# source: deadlock guard, not a measurement — a wait that a correct
# implementation satisfies at once, bounded so a broken one fails the test.
_GUARD = 5.0


class _Workers:
    """Thread-side counters of the workers a test starts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def blocking(self, error: Exception | None = None) -> str:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        self.started.set()
        self.release.wait(_GUARD)
        with self._lock:
            self.active -= 1
        if error is not None:
            raise error
        return "done"


@pytest.fixture
def workers():
    reset_semaphores()
    w = _Workers()
    yield w
    w.started.set()
    w.release.set()
    reset_semaphores()


@pytest.fixture
def warnings_(caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    return lambda: [r.getMessage() for r in caplog.records if r.name == _LOGGER]


async def _cancel_once_started(workers: _Workers, **kwargs) -> None:
    caller = asyncio.ensure_future(
        run_admitted(_TOOL, lambda: workers.blocking(**kwargs))
    )
    assert await asyncio.to_thread(workers.started.wait, _GUARD)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller


async def _admitted(func, *args):
    return await asyncio.wait_for(run_admitted(_TOOL, func, *args), _GUARD)


@pytest.mark.asyncio
async def test_cancelled_caller_holds_slot_until_worker_finishes(workers):
    assert current_budget(_TOOL) == 1
    await _cancel_once_started(workers)
    assert _get_semaphore(_TOOL).locked()

    second_ran = threading.Event()
    second = asyncio.ensure_future(run_admitted(_TOOL, second_ran.set))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not second.done()
    assert not second_ran.is_set()

    workers.release.set()
    await asyncio.wait_for(second, _GUARD)
    assert second_ran.is_set()
    assert workers.peak == 1


@pytest.mark.asyncio
async def test_result_and_error_reach_a_caller_that_waits(workers):
    assert await _admitted(lambda a, b: a + b, 2, 3) == 5

    def boom():
        raise ValueError("handler failed")

    with pytest.raises(ValueError, match="handler failed"):
        await _admitted(boom)
    # The slot of the failed call was released: this one is admitted.
    assert await _admitted(lambda: "next") == "next"
    assert not _get_semaphore(_TOOL).locked()


@pytest.mark.asyncio
async def test_abandoned_worker_success_is_logged(workers, warnings_):
    await _cancel_once_started(workers)
    assert warnings_() == []
    workers.release.set()
    await _admitted(lambda: None)
    assert warnings_() == [
        "consolidate worker completed after its caller was cancelled"
        " (0 abandoned still running)"
    ]


@pytest.mark.asyncio
async def test_abandoned_worker_error_is_logged_and_retrieved(workers, warnings_):
    await _cancel_once_started(workers, error=RuntimeError("late failure"))
    workers.release.set()
    await _admitted(lambda: None)
    assert warnings_() == [
        "consolidate worker raised RuntimeError after its caller was cancelled"
        " (0 abandoned still running)"
    ]


@pytest.mark.asyncio
async def test_abandoned_worker_cancelled_by_loop_teardown_is_logged(
    workers, warnings_
):
    before = asyncio.all_tasks()
    caller = asyncio.ensure_future(run_admitted(_TOOL, workers.blocking))
    assert await asyncio.to_thread(workers.started.wait, _GUARD)
    (worker,) = asyncio.all_tasks() - before - {caller}
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert warnings_() == [
        "consolidate worker was cancelled after its caller was cancelled"
        " (0 abandoned still running)"
    ]
    workers.release.set()
