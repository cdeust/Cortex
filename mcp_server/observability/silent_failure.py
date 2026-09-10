"""Shared instrumentation for components with a legitimate silent fallback.

source: ADR-0640"""

from __future__ import annotations

import logging
import threading

from mcp_server.observability import metrics

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
# component name -> "ExceptionType: message" of the most recent failure.
_last_error: dict[str, str] = {}
# component name -> count of note() calls this process (for status()).
_counts: dict[str, int] = {}


def note(component: str, exc: BaseException) -> None:
    """Record a swallowed failure for ``component``; log only the first.

    Precondition: called from within an ``except`` handler; ``component``
    is a stable dotted name (``"<module>.<mechanism>"``) identifying the
    failing mechanism, not the call site.
    Postcondition: on the first call for a given ``component`` in this
    process, emits one ``logger.warning`` naming the component and the
    exception. Every subsequent call for the same component is silent at
    the log level but still increments ``cortex_silent_failures_total``
    and updates the last-seen error in ``status()``. Never raises.
    """
    try:
        message = f"{type(exc).__name__}: {exc}"
        with _LOCK:
            is_first = component not in _last_error
            _last_error[component] = message
            _counts[component] = _counts.get(component, 0) + 1
        if is_first:
            logger.warning(
                "%s failed (fallback active, this component is now degraded; "
                "further failures logged at status() only, not re-logged): %s",
                component,
                message,
            )
        metrics.inc_counter("cortex_silent_failures_total", {"component": component})
    except Exception:  # noqa: BLE001, S110 — source: ADR-0640
        pass


def status() -> dict[str, dict[str, object]]:
    """Return ``{component: {"last_error": str, "count": int}}`` for every
    component that has failed at least once in this process.

    Precondition: none.
    Postcondition: empty dict iff ``note()`` has never been called this
    process. Read-only; never mutates state.
    """
    with _LOCK:
        return {
            component: {
                "last_error": _last_error[component],
                "count": _counts[component],
            }
            for component in _last_error
        }


def reset() -> None:
    """Test-only: clear all recorded failures."""
    with _LOCK:
        _last_error.clear()
        _counts.clear()
