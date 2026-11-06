"""Issue #728, slice 2: the status of workers that outlive their caller.

A cancelled tool call leaves its worker running. While it runs it is counted
in ``abandoned_work`` under ``in_flight``; when it ends it moves to ``ended``
under its outcome, and the log line names how many are still running.

Orderings are driven by ``threading.Event``; ``_GUARD`` only bounds a wait a
broken implementation would never satisfy. No verdict depends on elapsed time.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from mcp_server.handlers import abandoned_work
from mcp_server.handlers.admission import reset_semaphores, run_admitted

# source: mcp_server/handlers/latency_class.py — remember is interactive,
# budget 4 (admission override), so two held slots leave room for a third call.
_TOOL = "remember"
# source: deadlock guard, not a measurement.
_GUARD = 5.0
_LOGGER = "mcp_server.handlers.admission"


@pytest.fixture(autouse=True)
def _clean():
    reset_semaphores()
    abandoned_work.reset()
    yield
    reset_semaphores()
    abandoned_work.reset()


async def _abandon(func) -> asyncio.Future:
    """Start ``func`` admitted, wait until it runs, cancel its caller.

    Returns the worker future, which outlives the caller."""
    started = threading.Event()

    def body():
        started.set()
        return func()

    before = asyncio.all_tasks()
    caller = asyncio.ensure_future(run_admitted(_TOOL, body))
    assert await asyncio.to_thread(started.wait, _GUARD)
    (worker,) = asyncio.all_tasks() - before - {caller}
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    return worker


async def _settle(*workers: asyncio.Future) -> None:
    """Wait for the workers to end.

    ``asyncio.wait`` registers its done callback after admission's, so by the
    time it returns the outcome has been recorded."""
    _, pending = await asyncio.wait(workers, timeout=_GUARD)
    assert not pending


def _late_failure():
    raise RuntimeError("late failure")


@pytest.mark.asyncio
async def test_running_abandoned_worker_is_in_flight_until_it_ends():
    release = threading.Event()
    worker = await _abandon(lambda: release.wait(_GUARD))
    assert abandoned_work.snapshot() == {"in_flight": {_TOOL: 1}, "ended": {}}

    release.set()
    await _settle(worker)
    assert abandoned_work.snapshot() == {
        "in_flight": {},
        "ended": {_TOOL: {"completed": 1, "raised": 0, "cancelled": 0}},
    }


@pytest.mark.asyncio
async def test_each_outcome_is_counted_apart():
    release = threading.Event()

    def fails_after_release():
        release.wait(_GUARD)
        _late_failure()

    first = await _abandon(lambda: release.wait(_GUARD))
    second = await _abandon(fails_after_release)
    assert abandoned_work.snapshot()["in_flight"] == {_TOOL: 2}

    release.set()
    await _settle(first, second)
    assert abandoned_work.snapshot() == {
        "in_flight": {},
        "ended": {_TOOL: {"completed": 1, "raised": 1, "cancelled": 0}},
    }


@pytest.mark.asyncio
async def test_a_caller_that_waits_is_never_counted():
    assert await asyncio.wait_for(run_admitted(_TOOL, lambda: 7), _GUARD) == 7
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(run_admitted(_TOOL, _late_failure), _GUARD)
    assert abandoned_work.snapshot() == {"in_flight": {}, "ended": {}}


@pytest.mark.asyncio
async def test_same_outcome_adds_up_and_the_log_counts_down(caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    first_go, second_go = threading.Event(), threading.Event()
    first = await _abandon(lambda: first_go.wait(_GUARD))
    second = await _abandon(lambda: second_go.wait(_GUARD))

    first_go.set()
    await _settle(first)
    assert abandoned_work.snapshot()["in_flight"] == {_TOOL: 1}
    second_go.set()
    await _settle(second)

    assert abandoned_work.snapshot() == {
        "in_flight": {},
        "ended": {_TOOL: {"completed": 2, "raised": 0, "cancelled": 0}},
    }
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER] == [
        f"{_TOOL} worker completed after its caller was cancelled"
        " (1 abandoned still running)",
        f"{_TOOL} worker completed after its caller was cancelled"
        " (0 abandoned still running)",
    ]
