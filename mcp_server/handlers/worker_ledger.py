"""Per-tool record of admitted workers, for ``memory_stats`` (issue #728).

A caller cancelled while its worker thread runs gets no result, yet the work
goes on, and for a mutating tool its writes land. This ledger keeps, per tool,
the workers running now, those still running after their caller was cancelled,
and how each such abandoned worker ended. It is process-local: it describes
the server that answers the call, and restarts empty with it.

The admission callbacks write on the event-loop thread; ``memory_stats`` reads
on a worker thread. Both go through one lock.

source: issue #728"""

from __future__ import annotations

import threading
from collections import Counter

_LOCK = threading.Lock()
_active: Counter[str] = Counter()
_abandoned_running: Counter[str] = Counter()
# (tool, outcome) -> number of abandoned workers that ended that way.
_abandoned_ended: Counter[tuple[str, str]] = Counter()

# The three ways a worker future can end, named as ``memory_stats`` reports them.
# source: asyncio.Future states (cancelled / exception / result)
OUTCOMES = ("completed", "raised", "cancelled")


def worker_started(tool_name: str) -> None:
    with _LOCK:
        _active[tool_name] += 1


def caller_abandoned(tool_name: str) -> None:
    """The caller of a running worker was cancelled; the worker goes on."""
    with _LOCK:
        _abandoned_running[tool_name] += 1


def worker_ended(tool_name: str, abandoned_outcome: str | None) -> None:
    """A worker ended; ``abandoned_outcome`` (one of ``OUTCOMES``) when its
    caller had been cancelled, else None. One lock covers both counts, so a
    reader never sees an abandoned worker that is no longer active."""
    with _LOCK:
        _active[tool_name] -= 1
        if abandoned_outcome is not None:
            _abandoned_running[tool_name] -= 1
            _abandoned_ended[(tool_name, abandoned_outcome)] += 1


def abandoned_after_end(tool_name: str, outcome: str) -> None:
    """The caller was cancelled after its worker had ended with ``outcome``."""
    with _LOCK:
        _abandoned_ended[(tool_name, outcome)] += 1


def report() -> dict[str, dict[str, int]]:
    """Per tool with any recorded worker: running now, running abandoned, and
    abandoned workers ended per outcome since the process started.

    The ``memory_stats`` call that reads this counts as one running worker."""
    with _LOCK:
        # A running abandoned worker is also active (see worker_ended).
        tools = set(+_active) | {tool for (tool, _) in _abandoned_ended}
        return {
            tool: {
                "active": _active[tool],
                "abandoned_running": _abandoned_running[tool],
                **{
                    f"abandoned_{outcome}": _abandoned_ended[(tool, outcome)]
                    for outcome in OUTCOMES
                },
            }
            for tool in sorted(tools)
        }


def reset() -> None:
    """For tests only."""
    with _LOCK:
        _active.clear()
        _abandoned_running.clear()
        _abandoned_ended.clear()
