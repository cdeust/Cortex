"""The broker's two request classes, reserved capacity and backpressure.

Each class has its own slots, sized like the store pool it runs on
(``interactive_slots`` = ``POOL_INTERACTIVE_MAX``, ``background_slots`` =
``POOL_BATCH_MAX``): background work can never take an interactive slot, so
interactive requests (recall, remember, hooks) keep their capacity however
much consolidation is queued, and no class runs more requests than it has
connections (A1 measured pool timeouts when 10 workers shared 8 interactive
connections). Each class has a bounded FIFO queue. A request that
finds its queue full waits for a place until its own deadline and is then
refused, explicitly; a request whose deadline passes while queued is
answered with an error and never executed. Nothing is dropped silently
(the capture mailbox rule, ADR-0511).

source: ADR-1112 decision 4
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SchedulerPolicy:
    interactive_slots: int
    background_slots: int
    queue_limit: int

    def __post_init__(self) -> None:
        if self.interactive_slots < 1 or self.background_slots < 1:
            raise ValueError("each class needs at least one slot")
        if self.queue_limit < 1:
            raise ValueError("queue_limit must be positive")

    @property
    def workers(self) -> int:
        return self.interactive_slots + self.background_slots


@dataclass
class Task:
    """One request on its way through the scheduler."""

    request_class: str
    deadline: float  # monotonic
    run: Callable[[], Any]
    enqueued_at: float = field(default_factory=time.monotonic)
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None
    executed: bool = False


class BrokerBusyError(RuntimeError):
    """The request's class queue stayed full until its deadline."""


class DeadlineExpiredError(TimeoutError):
    """The request's deadline passed before a worker could run it."""


class Scheduler:
    def __init__(self, policy: SchedulerPolicy) -> None:
        self.policy = policy
        self._queues: dict[str, deque[Task]] = {
            "interactive": deque(),
            "background": deque(),
        }
        self._busy = {"interactive": 0, "background": 0}
        self._cond = threading.Condition()
        self._stopping = False

    def submit(self, task: Task) -> None:
        """Queue ``task`` or raise ``BrokerBusyError`` at its deadline."""
        queue = self._queues[task.request_class]
        with self._cond:
            while len(queue) >= self.policy.queue_limit and not self._stopping:
                left = task.deadline - time.monotonic()
                if left <= 0:
                    raise BrokerBusyError(
                        f"{task.request_class} queue full "
                        f"({self.policy.queue_limit}) until the deadline"
                    )
                self._cond.wait(left)
            queue.append(task)
            self._cond.notify_all()

    def _next(self) -> Task | None:
        interactive, background = (
            self._queues["interactive"],
            self._queues["background"],
        )
        if interactive and self._busy["interactive"] < self.policy.interactive_slots:
            return interactive.popleft()
        if background and self._busy["background"] < self.policy.background_slots:
            return background.popleft()
        return None

    def take(self) -> Task | None:
        """The next runnable task, or None once stopping with nothing left."""
        with self._cond:
            while True:
                task = self._next()
                if task is not None:
                    self._busy[task.request_class] += 1
                    self._cond.notify_all()  # a queue slot freed up
                    return task
                if self._stopping:
                    return None
                self._cond.wait()

    def finish(self, task: Task) -> None:
        with self._cond:
            self._busy[task.request_class] -= 1
            self._cond.notify_all()
        task.done.set()

    def execute(self, task: Task) -> None:
        """Run ``task`` unless its deadline already passed, then finish it."""
        try:
            if time.monotonic() >= task.deadline:
                raise DeadlineExpiredError(
                    "deadline passed before the request was dispatched; not executed"
                )
            task.executed = True
            task.result = task.run()
        except BaseException as exc:  # noqa: BLE001 — returned to the requester, never swallowed
            task.error = exc
        finally:
            self.finish(task)

    def idle(self) -> bool:
        with self._cond:
            return not any(self._queues.values()) and not any(self._busy.values())

    def stop(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()

    def snapshot(self) -> dict[str, int]:
        with self._cond:
            return {
                "queued_interactive": len(self._queues["interactive"]),
                "queued_background": len(self._queues["background"]),
                "busy_interactive": self._busy["interactive"],
                "busy_background": self._busy["background"],
            }
