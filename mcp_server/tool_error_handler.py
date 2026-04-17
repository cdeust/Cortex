"""Friendly error handling for MCP tool calls.

Wraps handler exceptions so users never see raw Python tracebacks.
Database connection errors get a helpful setup guide instead.

Usage in tool registries:
    from mcp_server.tool_error_handler import safe_handler

    async def tool_remember(...) -> str:
        result = await safe_handler(remember.handler, {...})
        return result
"""

from __future__ import annotations

import json
from typing import Any, Callable, Coroutine

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


def _classify_error(exc: Exception) -> tuple[str, str]:
    """Classify an exception into a user-friendly category and message."""
    exc_lower = (type(exc).__name__ + " " + str(exc)).lower()

    if any(
        kw in exc_lower
        for kw in [
            'type "vector" does not exist',
            "extension",
            "pg_trgm",
        ]
    ):
        return "missing_extension", _EXTENSION_GUIDE

    if any(
        kw in exc_lower
        for kw in [
            "connection refused",
            "could not connect",
            "no such host",
            "connection reset",
            "does not exist",
            "operationalerror",
            "role",
            "password authentication",
            "timeout",
        ]
    ):
        return "database_not_connected", _DB_SETUP_GUIDE

    return type(exc).__name__, str(exc)


async def safe_handler(
    handler_fn: Callable[..., Coroutine[Any, Any, dict]],
    args: dict[str, Any],
    tool_name: str | None = None,
) -> str:
    """Call a handler and return JSON, catching errors gracefully.

    When ``tool_name`` is provided, the call is gated by the per-tool
    admission semaphore (Phase 5). This bounds concurrency so one client
    cannot DoS a tool by hammering it. When omitted, the call runs
    unadmitted for backward compat with the pre-Phase-5 surface —
    registries should always pass ``tool_name`` post-v3.13.0.

    On success: returns json.dumps(result).
    On DB errors: returns a friendly setup guide.
    On other errors: returns error type + message (no traceback).
    """
    try:
        if tool_name:
            from mcp_server.handlers.admission import admit

            async with admit(tool_name):
                result = await handler_fn(args)
        else:
            result = await handler_fn(args)
        return json.dumps(result, indent=2, default=str)
    except Exception as exc:
        error_type, message = _classify_error(exc)
        return json.dumps(
            {
                "error": error_type,
                "message": message,
                "hint": (
                    "If this persists, check that PostgreSQL is running "
                    "and DATABASE_URL is set correctly."
                )
                if error_type not in ("missing_extension", "database_not_connected")
                else None,
            },
            indent=2,
            default=str,
        )
