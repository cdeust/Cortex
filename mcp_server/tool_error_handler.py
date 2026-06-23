"""Friendly error handling for MCP tool calls.

Wraps handler exceptions so users never see raw Python tracebacks.
Database connection errors get a helpful setup guide instead.

Phase 5 adds two transparent safety nets on top of error handling:
  * per-tool admission semaphore (Phase 5 step 5)
  * asyncio.to_thread offload so handler bodies (which call sync
    DB methods) run on a worker thread instead of blocking the event
    loop

Issue #17 (PSGSupport): handlers that declare ``output_schema`` were
rejected by FastMCP with ``structured_content must be a dict or None.
Got str: '{...}'`` because this wrapper used to ``json.dumps`` the
result before returning. FastMCP 2.x validates the return shape
against the declared schema and rejects strings. Fix: return the
dict directly. The handler contract IS dict-or-None (Liskov: every
``mcp__cortex__*`` handler now uniformly satisfies the same interface).

Usage in tool registries:
    from mcp_server.tool_error_handler import safe_handler

    async def tool_remember(...) -> dict:
        result = await safe_handler(remember.handler, {...}, tool_name="remember")
        return result
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from mcp_server.shared.json_native import to_json_native

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


def _run_coroutine_on_thread(
    handler_fn: Callable[..., Coroutine[Any, Any, dict]],
    args: dict[str, Any],
) -> dict:
    """Run an async handler's coroutine on a fresh event loop in a worker thread.

    Used by ``safe_handler`` under ``asyncio.to_thread`` to give real
    parallelism when the handler body is effectively synchronous
    (calls sync store methods inside an ``async def``).

    Each worker thread gets its own event loop; no cross-thread loop
    sharing. The loop is closed at the end so thread reuse doesn't
    carry over state.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(handler_fn(args))
    finally:
        try:
            loop.close()
        except Exception:
            pass


async def safe_handler(
    handler_fn: Callable[..., Coroutine[Any, Any, dict]],
    args: dict[str, Any],
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Call a handler and return its dict, catching errors gracefully.

    When ``tool_name`` is provided:
      * The call is gated by the per-tool admission semaphore (Phase 5
        step 5). Bounds concurrency so one client cannot DoS a tool by
        hammering it.
      * The handler runs on a worker thread via ``asyncio.to_thread``
        (Phase 5 step 4). The handler body — which calls sync DB
        methods — no longer blocks the event loop, and two concurrent
        tool invocations genuinely run in parallel (the pool gives each
        worker its own DB connection).

    When ``tool_name`` is omitted the call runs in-line on the caller's
    event loop without admission (backward-compat for code paths not
    yet migrated).

    Contract (issue #17 — Liskov enforcement across all MCP handlers):
      precondition: ``handler_fn`` is an async callable returning a dict.
      postcondition: returns a ``dict[str, Any]``. Never a JSON string.
                     FastMCP 2.x validates structured content against
                     the declared ``output_schema`` and rejects strings.

    On success: returns the handler's dict verbatim.
    On DB errors: returns a friendly setup-guide dict.
    On other errors: returns an error-type/message dict (no traceback).
    """
    try:
        if tool_name:
            from mcp_server.handlers.admission import admit
            from mcp_server.observability import metrics

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
            result = await handler_fn(args)
        # Defensive: every handler must already return a dict per its
        # ``output_schema``. If a handler regresses to None we surface
        # an empty dict so FastMCP's structured-content validator does
        # not reject the response.
        if result is None:
            return {}
        # Single wire format across backends. The PG store returns
        # ``datetime``/``numpy`` scalars where the SQLite store returns
        # ``str``/``float``; FastMCP can only build ``structuredContent``
        # from JSON-native values, so a non-native field silently drops
        # structuredContent and the client rejects the call ("outputSchema
        # defined but no structured output returned"). Normalizing here —
        # the one boundary every handler crosses — guarantees an identical,
        # schema-friendly return shape regardless of which backend produced
        # it. Native dicts (e.g. remember) pass through unchanged.
        return to_json_native(result)
    except Exception as exc:
        error_type, message = _classify_error(exc)
        if tool_name:
            try:
                from mcp_server.observability import metrics

                metrics.inc_counter(
                    "cortex_tool_calls_total",
                    {"tool": tool_name, "status": "error"},
                )
            except Exception:
                pass
        return {
            "error": error_type,
            "message": message,
            "hint": (
                "If this persists, check that PostgreSQL is running "
                "and DATABASE_URL is set correctly."
            )
            if error_type not in ("missing_extension", "database_not_connected")
            else None,
        }
