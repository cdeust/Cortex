"""Shared instrumentation for components with a legitimate silent fallback.

Context (audit 2026-07-11, docs/audits/silent-except-audit-2026-07-11.md):
Two production incidents in one night were both the same shape — a broad
``except Exception`` guarding a component that has a real, intentional
fallback (skip re-ranking, skip a graph expansion) caught a bug in the
*mechanism itself* and silently disabled it for the rest of the process,
with zero log signal:

  1. FlashRank reranker (fix bb1c581f): ``_ensure_reranker()`` swallowed a
     ``NoSuchFile`` from an unset ``cache_dir`` default; re-ranking was
     skipped for months.
  2. Spreading activation (recall_pipeline.py, fixed on a concurrent
     branch): a non-recursive ``WITH`` in the PL/pgSQL body raised a SQL
     error on every call since the query was introduced; masked by
     ``except Exception: return candidates``.

This module is the reusable half of the fix pattern both incidents ended
up needing independently: log the FIRST failure of a named component
(so operators see it once, not once per call), keep every subsequent
failure silent (anti-spam — the fallback is legitimate and must not spam
logs), always bump a Prometheus counter (so failure RATE is visible even
after the anti-spam gate closes), and expose the last-seen state via
``status()`` so a health check or doctor command can ask "is X currently
degraded?" without grepping logs.

Precondition on every call to ``note()``: the caller is already INSIDE an
``except`` block whose fallback is intentional and behavior-preserving —
this module never changes what the caller returns, only whether the
failure is observable.
Postcondition: ``note()`` never raises (Move 3: instrumentation must not
itself become a new failure mode) and never blocks past a few microseconds
(single dict lookup + counter increment under a lock).
"""

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
    except Exception:  # noqa: BLE001, S110 — instrumentation must never break the caller
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
