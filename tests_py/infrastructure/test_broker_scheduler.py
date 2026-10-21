"""The broker's two request classes (ADR-1112 decision 4, acceptance A5).

source: ADR-1112
"""

from __future__ import annotations

import threading
import time

import pytest

from mcp_server.infrastructure.broker_scheduler import (
    BrokerBusyError,
    DeadlineExpiredError,
    Scheduler,
    SchedulerPolicy,
    Task,
)


def _start(scheduler: Scheduler) -> list[threading.Thread]:
    def work():
        while (task := scheduler.take()) is not None:
            scheduler.execute(task)

    workers = [
        threading.Thread(target=work, daemon=True)
        for _ in range(scheduler.policy.workers)
    ]
    for worker in workers:
        worker.start()
    return workers


def _task(cls: str, run, budget: float = 10.0) -> Task:
    return Task(request_class=cls, deadline=time.monotonic() + budget, run=run)


def test_policy_rejects_a_class_without_slots():
    with pytest.raises(ValueError):
        SchedulerPolicy(interactive_slots=0, background_slots=1, queue_limit=1)
    with pytest.raises(ValueError):
        SchedulerPolicy(interactive_slots=1, background_slots=0, queue_limit=1)


def test_interactive_is_served_while_background_saturates_its_share():
    """A5 at the scheduler: background holds every worker it may use and has
    a full queue behind it; an interactive request still runs at once."""
    scheduler = Scheduler(
        SchedulerPolicy(interactive_slots=1, background_slots=2, queue_limit=4)
    )
    _start(scheduler)
    release = threading.Event()
    blocked = [_task("background", release.wait) for _ in range(2 + 4)]
    for task in blocked:
        scheduler.submit(task)
    deadline = time.monotonic() + 5
    while scheduler.snapshot()["busy_background"] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert scheduler.snapshot()["busy_background"] == 2  # its slots
    started = time.monotonic()
    interactive = _task("interactive", lambda: "served")
    scheduler.submit(interactive)
    assert interactive.done.wait(2.0)
    assert interactive.result == "served"
    assert time.monotonic() - started < 1.0
    release.set()
    for task in blocked:
        assert task.done.wait(5.0) and task.error is None
    scheduler.stop()


def test_a_full_queue_refuses_at_the_callers_deadline():
    scheduler = Scheduler(
        SchedulerPolicy(interactive_slots=1, background_slots=1, queue_limit=1)
    )
    release = threading.Event()
    _start(scheduler)
    scheduler.submit(_task("background", release.wait))  # running
    time.sleep(0.05)
    scheduler.submit(_task("background", release.wait))  # queued: the limit
    started = time.monotonic()
    with pytest.raises(BrokerBusyError):
        scheduler.submit(_task("background", release.wait, budget=0.2))
    assert 0.15 <= time.monotonic() - started < 2.0
    release.set()
    scheduler.stop()


def test_a_request_whose_deadline_passed_in_the_queue_is_not_executed():
    scheduler = Scheduler(
        SchedulerPolicy(interactive_slots=1, background_slots=1, queue_limit=4)
    )
    release = threading.Event()
    _start(scheduler)
    scheduler.submit(_task("background", release.wait))
    ran: list[int] = []
    late = _task("background", lambda: ran.append(1), budget=0.05)
    scheduler.submit(late)
    time.sleep(0.2)
    release.set()
    assert late.done.wait(2.0)
    assert isinstance(late.error, DeadlineExpiredError)
    assert late.executed is False and ran == []
    scheduler.stop()


def test_errors_are_returned_to_the_requester_not_swallowed():
    scheduler = Scheduler(
        SchedulerPolicy(interactive_slots=1, background_slots=1, queue_limit=4)
    )
    _start(scheduler)

    def boom():
        raise RuntimeError("store failure")

    task = _task("interactive", boom)
    scheduler.submit(task)
    assert task.done.wait(2.0)
    assert isinstance(task.error, RuntimeError) and task.executed
    assert scheduler.idle()
    scheduler.stop()
