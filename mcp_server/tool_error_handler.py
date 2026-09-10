"""Friendly error handling for MCP tool calls.

source: ADR-0691"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from mcp.server.mcpserver.exceptions import ToolError

from mcp_server.shared.json_native import to_json_native
from mcp_server.handlers.admission import admit
from mcp_server.handlers.request_transaction import handler_transaction_scope
from mcp_server.observability import metrics

logger = logging.getLogger(__name__)

_DB_SETUP_GUIDE = (
    "Cortex could not connect to PostgreSQL. "
    "This usually means the database is not set up yet.\n\n"
    "Quick fix:\n"
    "  brew install postgresql@17 pgvector\n"
    "  brew services start postgresql@17\n"
    "  createdb cortex\n"
    '  psql -d cortex -c "CREATE EXTENSION IF NOT EXISTS vector; '
    'CREATE EXTENSION IF NOT EXISTS pg_trgm;"\n'
    "  export DATABASE_URL=postgresql://localhost:5432/cortex\n\n"
    "Then restart Claude Code. Cortex will auto-initialize the schema."
)

_EXTENSION_GUIDE = (
    "Cortex requires the pgvector and pg_trgm PostgreSQL extensions.\n\n"
    "Install them:\n"
    "  brew install pgvector  # macOS\n"
    '  psql -d cortex -c "CREATE EXTENSION IF NOT EXISTS vector; '
    'CREATE EXTENSION IF NOT EXISTS pg_trgm;"\n\n'
    "Then restart Claude Code."
)

_MISSING_EXTENSION_PHRASES = [
    'type "vector" does not exist',
    "extension",
    "pg_trgm",
]

# source: ADR-0691


_CONNECTION_FAILURE_PHRASES = [
    "connection refused",
    "could not connect",
    "could not translate host name",
    "no such host",
    "connection reset",
    "server closed the connection",
    "the database system is starting up",
    "password authentication failed",
    "connection timed out",
    "timeout expired",  # psycopg connect-timeout wording
]


def _classify_error(exc: Exception) -> tuple[str, str]:
    """Classify an exception into a user-friendly category and message."""
    exc_lower = (type(exc).__name__ + " " + str(exc)).lower()

    # source: ADR-0691

    if "explicit database_url unreachable" in exc_lower:
        return "explicit_database_url_unreachable", str(exc)

    if any(kw in exc_lower for kw in _MISSING_EXTENSION_PHRASES):
        return "missing_extension", _EXTENSION_GUIDE

    if any(kw in exc_lower for kw in _CONNECTION_FAILURE_PHRASES):
        return "database_not_connected", _DB_SETUP_GUIDE

    return type(exc).__name__, str(exc)


def _run_coroutine_on_thread(
    handler_fn: Callable[..., Awaitable[dict]],
    args: dict[str, Any],
) -> dict:
    """Run an async handler's coroutine on a fresh event loop in a worker thread.

    Used by ``safe_handler`` under ``asyncio.to_thread`` to give real
    parallelism when the handler body is effectively synchronous
    (calls sync store methods inside an ``async def``).

    source: ADR-0691"""
    loop = asyncio.new_event_loop()
    try:
        with handler_transaction_scope():
            return loop.run_until_complete(handler_fn(args))
    finally:
        try:
            loop.close()
        except RuntimeError:
            # Loop still running (handler leaked a task); the thread-local
            # loop is abandoned and reclaimed at interpreter exit.
            pass


async def safe_handler(
    handler_fn: Callable[..., Awaitable[dict]],
    args: dict[str, Any],
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Call a handler and return its dict, catching errors gracefully.

    source: ADR-0691

    When ``tool_name`` is omitted, admission and named metrics remain disabled,
    but offload and transaction isolation are preserved. This keeps concurrent
    compatibility calls from sharing the event-loop thread's SQLite handle.

    source: ADR-0691"""
    try:
        if tool_name:
            async with admit(tool_name):
                with metrics.Timer(
                    "cortex_tool_duration_seconds",
                    {"tool": tool_name},
                ):
                    result = await asyncio.to_thread(
                        _run_coroutine_on_thread, handler_fn, args
                    )
            metrics.inc_counter(
                "cortex_tool_calls_total",
                {"tool": tool_name, "status": "ok"},
            )
        else:
            result = await asyncio.to_thread(_run_coroutine_on_thread, handler_fn, args)
        # source: ADR-0691

        if result is None:
            return {}
        # source: ADR-0691

        return to_json_native(result)
    except Exception as exc:
        # source: ADR-0691

        logger.exception(
            "safe_handler caught %s in tool %r",
            type(exc).__name__,
            tool_name or "<unnamed>",
        )
        error_type, message = _classify_error(exc)
        if tool_name:
            try:
                metrics.inc_counter(
                    "cortex_tool_calls_total",
                    {"tool": tool_name, "status": "error"},
                )
            # source: ADR-0691

            except Exception as metrics_exc:  # noqa: BLE001 — source: ADR-0691
                logger.debug("error-counter increment failed: %s", metrics_exc)
        # source: ADR-0691

        full_message = f"{error_type}: {message}"
        raise ToolError(full_message) from exc
