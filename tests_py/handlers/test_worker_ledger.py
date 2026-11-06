"""Issue #728: what ``memory_stats`` reports about workers whose caller left.

Each test drives the real ``run_admitted`` and orders the worker on
``threading.Event``; ``_GUARD`` only bounds a wait a broken implementation
would never satisfy. No verdict depends on elapsed time.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from mcp_server.handlers import memory_stats, worker_ledger
from mcp_server.handlers.admission import (
    _Run,
    current_budget,
    reset_semaphores,
    run_admitted,
)

# source: mcp_server/handlers/admission.py — remember is a mutating tool, budget 4.
_TOOL = "remember"
# source: deadlock guard, not a measurement (same as test_admission_cancellation).
_GUARD = 5.0


def _row(**counts: int) -> dict[str, int]:
    row = {"active": 0, "abandoned_running": 0}
    row.update({f"abandoned_{o}": 0 for o in worker_ledger.OUTCOMES})
    row.update(counts)
    return row


@pytest.fixture
def gate():
    reset_semaphores()
    worker_ledger.reset()
    started, release = threading.Event(), threading.Event()

    def blocking(error: Exception | None = None) -> str:
        started.set()
        release.wait(_GUARD)
        if error is not None:
            raise error
        return "written"

    yield started, release, blocking
    started.set()
    release.set()
    reset_semaphores()
    worker_ledger.reset()


async def _abandon(started, func) -> None:
    caller = asyncio.ensure_future(run_admitted(_TOOL, func))
    assert await asyncio.to_thread(started.wait, _GUARD)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller


async def _drain() -> None:
    """Run the tool's whole budget at once: every call waits at one barrier
    until all hold a slot, so every abandoned worker has released its own.
    Its release and its ledger record are one callback (``_Run.worker_done``).
    """
    budget = current_budget(_TOOL)
    barrier = threading.Barrier(budget, timeout=_GUARD)
    calls = [run_admitted(_TOOL, barrier.wait) for _ in range(budget)]
    await asyncio.wait_for(asyncio.gather(*calls), _GUARD)


@pytest.mark.asyncio
async def test_abandoned_mutation_is_running_then_completed(gate):
    started, release, blocking = gate
    await _abandon(started, blocking)
    assert worker_ledger.report() == {_TOOL: _row(active=1, abandoned_running=1)}

    release.set()
    await _drain()
    assert worker_ledger.report() == {_TOOL: _row(abandoned_completed=1)}


@pytest.mark.asyncio
async def test_abandoned_worker_that_raises_is_counted_as_raised(gate):
    started, release, blocking = gate
    await _abandon(started, lambda: blocking(RuntimeError("late failure")))
    release.set()
    await _drain()
    assert worker_ledger.report() == {_TOOL: _row(abandoned_raised=1)}


@pytest.mark.asyncio
async def test_awaited_calls_leave_no_abandoned_count(gate):
    assert await asyncio.wait_for(run_admitted(_TOOL, lambda: "ok"), _GUARD) == "ok"

    def boom():
        raise ValueError("handler failed")

    with pytest.raises(ValueError):
        await asyncio.wait_for(run_admitted(_TOOL, boom), _GUARD)
    assert worker_ledger.report() == {}


@pytest.mark.asyncio
async def test_memory_stats_returns_the_ledger(gate):
    started, release, blocking = gate
    await _abandon(started, blocking)
    stats = await asyncio.to_thread(asyncio.run, memory_stats.handler())
    assert stats["tool_workers"] == {_TOOL: _row(active=1, abandoned_running=1)}


@pytest.mark.asyncio
async def test_two_abandoned_workers_are_counted_twice(gate):
    _, release, _ = gate
    entered = [threading.Event(), threading.Event()]

    def worker(i: int) -> None:
        entered[i].set()
        release.wait(_GUARD)

    for i in (0, 1):
        await _abandon(entered[i], lambda i=i: worker(i))
    assert worker_ledger.report() == {_TOOL: _row(active=2, abandoned_running=2)}

    release.set()
    await _drain()
    assert worker_ledger.report() == {_TOOL: _row(abandoned_completed=2)}


@pytest.mark.asyncio
async def test_a_worker_whose_caller_waits_is_active_not_abandoned(gate):
    started, release, blocking = gate
    caller = asyncio.ensure_future(run_admitted(_TOOL, blocking))
    assert await asyncio.to_thread(started.wait, _GUARD)
    assert worker_ledger.report() == {_TOOL: _row(active=1)}
    release.set()
    assert await asyncio.wait_for(caller, _GUARD) == "written"
    assert worker_ledger.report() == {}


async def _cancel_after_end(worker: asyncio.Future) -> None:
    """Drive one admitted run whose caller is cancelled after its worker ended."""
    sem = asyncio.Semaphore(1)
    await sem.acquire()
    worker_ledger.worker_started(_TOOL)
    run = _Run(_TOOL, sem, worker)
    run.worker_done(worker)
    run.caller_cancelled()
    assert not sem.locked()


@pytest.mark.asyncio
async def test_caller_cancelled_after_the_worker_ended(gate, caplog):
    caplog.set_level(logging.WARNING, logger="mcp_server.handlers.admission")
    loop = asyncio.get_running_loop()
    for _ in range(2):
        done = loop.create_future()
        done.set_result("written")
        await _cancel_after_end(done)
    cancelled = loop.create_future()
    cancelled.cancel()
    await _cancel_after_end(cancelled)

    assert worker_ledger.report() == {
        _TOOL: _row(abandoned_completed=2, abandoned_cancelled=1)
    }
    assert [r.getMessage() for r in caplog.records] == [
        "remember worker completed after its caller was cancelled",
        "remember worker completed after its caller was cancelled",
        "remember worker was cancelled after its caller was cancelled",
    ]
