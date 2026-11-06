"""Status of tool workers that keep running after their caller was cancelled.

``asyncio.to_thread`` cannot stop a running thread, so a cancelled tool call
leaves its worker to finish on its own (issue #728). A mutating tool's write
then lands, or fails, after the client stopped listening. This registry makes
that state readable: how many abandoned workers are still running per tool,
and how each one that ended did (completed, raised, cancelled).

The counts are process-local and start at zero with each server process. They
say nothing about which rows a worker wrote; a tool's ``readOnlyHint`` says
whether its worker can write at all.

source: issue #728 (acceptance: "report in-flight mutation status and work
completing after client abandonment")"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Literal

Outcome = Literal["completed", "raised", "cancelled"]

_OUTCOMES: tuple[Outcome, ...] = ("completed", "raised", "cancelled")

_LOCK = threading.Lock()
_in_flight: dict[str, int] = defaultdict(int)
_ended: dict[str, dict[Outcome, int]] = {}


def record_abandoned(tool_name: str) -> None:
    """Count a worker whose caller was cancelled while it still runs."""
    with _LOCK:
        _in_flight[tool_name] += 1


def record_ended(tool_name: str, outcome: Outcome) -> int:
    """Move one abandoned worker of ``tool_name`` to its outcome.

    Returns how many abandoned workers of that tool are still running."""
    with _LOCK:
        _in_flight[tool_name] -= 1
        ended = _ended.setdefault(tool_name, dict.fromkeys(_OUTCOMES, 0))
        ended[outcome] += 1
        return _in_flight[tool_name]


def snapshot() -> dict[str, dict]:
    """Return ``{"in_flight": {tool: n}, "ended": {tool: {outcome: n}}}``.

    Tools with no running abandoned worker are left out of ``in_flight``."""
    with _LOCK:
        return {
            "in_flight": {t: n for t, n in sorted(_in_flight.items()) if n},
            "ended": {t: dict(c) for t, c in sorted(_ended.items())},
        }


def reset() -> None:
    """Drop all counts. For tests only."""
    with _LOCK:
        _in_flight.clear()
        _ended.clear()
