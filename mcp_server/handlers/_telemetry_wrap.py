"""Telemetry wrapping helper for handler entry points.

Wrap a handler's ``handler(args)`` coroutine with this and the call is
timed + recorded against the telemetry counters. Response byte volume uses
the SDK's UTF-8 text-content serialization, after JSON-native normalization;
it excludes the MCP transport envelope and structured-content duplication.

Usage:

    from mcp_server.handlers._telemetry_wrap import instrument

    handler = instrument("recall", _handler_impl,
                         result_count_key="results")
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable

from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.shared.json_native import to_json_native
from mcp_server.shared.telemetry_context import operation_metrics

HandlerFn = Callable[[dict[str, Any] | None], Awaitable[dict[str, Any]]]
logger = logging.getLogger(__name__)


def _safe_json_len(args: dict[str, Any] | None) -> int:
    if not args:
        return 0
    try:
        return len(json.dumps(args, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        logger.warning("Cannot serialize telemetry input", exc_info=True)
        return 0


def _response_bytes(result: dict[str, Any] | None) -> int:
    """UTF-8 bytes of the MCP text response, excluding the transport envelope."""
    if result is None:
        return 0
    try:
        # source: MCP SDK utilities/func_metadata.py::_convert_to_content;
        # safe_handler normalizes JSON-native values before SDK serialization.
        return len(to_json(to_json_native(result), fallback=str, indent=2))
    except (TypeError, ValueError):
        logger.warning("Cannot serialize telemetry output", exc_info=True)
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
                   one telemetry sample (op, latency_ms, bytes_in/out,
                   result_count, retrieval work, ok) and re-raises any exception
                   unchanged after marking ok=False.
    """

    async def wrapped(args: dict[str, Any] | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        ok = True
        result: dict[str, Any] | None = None
        with operation_metrics():
            try:
                result = await fn(args)
                return result  # noqa: RET504 — read by finally's telemetry sample
            except BaseException:
                ok = False
                raise
            finally:
                telemetry.record(
                    op,
                    # source: SI prefix milli; perf_counter returns seconds.
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    bytes_in=_safe_json_len(args),
                    bytes_out=_response_bytes(result),
                    result_count=_result_count(result, result_count_key),
                    ok=ok,
                )

    return wrapped
