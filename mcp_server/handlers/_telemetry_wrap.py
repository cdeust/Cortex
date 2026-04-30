"""Telemetry wrapping helper for handler entry points.

Wrap a handler's ``handler(args)`` coroutine with this and the call is
timed + recorded against the telemetry counters. Negligible overhead
(<1ms measured): one ``perf_counter`` pair, one JSON-len, one dispatch
to ``telemetry.record``.

Usage:

    from mcp_server.handlers._telemetry_wrap import instrument

    handler = instrument("recall", _handler_impl,
                         result_count_key="results")
"""

from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable

from mcp_server.core import telemetry

HandlerFn = Callable[[dict[str, Any] | None], Awaitable[dict[str, Any]]]


def _safe_json_len(args: dict[str, Any] | None) -> int:
    if not args:
        return 0
    try:
        return len(json.dumps(args, default=str))
    except (TypeError, ValueError):
        return 0


def _result_count(result: dict[str, Any] | None, key: str | None) -> int:
    if not isinstance(result, dict) or key is None:
        return 0
    val = result.get(key)
    if isinstance(val, list):
        return len(val)
    if isinstance(val, int):
        return val
    return 0


def instrument(
    op: str,
    fn: HandlerFn,
    *,
    result_count_key: str | None = None,
) -> HandlerFn:
    """Return an awaitable wrapper that records telemetry around ``fn``.

    precondition: ``fn`` is an async callable accepting a single
                  ``args`` dict and returning a dict.
    postcondition: every call to the returned wrapper records exactly
                   one telemetry sample (op, latency_ms, bytes_in,
                   result_count, ok) and re-raises any exception
                   unchanged after marking ok=False.
    """

    async def wrapped(args: dict[str, Any] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        ok = True
        result: dict[str, Any] = {}
        try:
            result = await fn(args)
            return result
        except Exception:
            ok = False
            raise
        finally:
            telemetry.record(
                op,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                bytes_in=_safe_json_len(args),
                result_count=_result_count(result, result_count_key),
                ok=ok,
            )

    return wrapped
