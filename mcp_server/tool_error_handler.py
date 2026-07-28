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

Issue (2026-07-14): on the ERROR path this wrapper still returned a
``{"error", "message", "hint"}`` dict. That dict is not a valid
instance of ANY tool's ``outputSchema`` (recall requires "memories",
remember requires "stored"/"action" -- mcp/server/lowlevel/server.py's
``call_tool`` handler validates ``structuredContent`` against
``tool.outputSchema`` via ``jsonschema.validate`` and, on mismatch,
discards our classified message and replaces it with its own generic
``Output validation error: '<field>' is a required property``). Every
one of the ~50 tools registered through ``safe_handler`` was affected.
Fix: raise ``fastmcp.exceptions.ToolError`` instead of returning the
error dict. FastMCP's own ``call_tool`` (fastmcp/server/server.py)
re-raises a ``FastMCPError`` subclass unchanged (no re-wrapping), and
the low-level MCP server's ``call_tool`` handler builds the
``isError=True`` result from ``str(exc)`` directly -- BEFORE any
outputSchema check, which only runs on the non-error branch. Raising
therefore reaches the client with the classified message intact.

Usage in tool registries:
    from mcp_server.tool_error_handler import safe_handler

    async def tool_remember(...) -> dict:
        result = await safe_handler(remember.handler, {...}, tool_name="remember")
        return result
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

from fastmcp.exceptions import ToolError

from mcp_server.shared.json_native import to_json_native
from mcp_server.handlers.admission import admit
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


def _classify_error(exc: Exception) -> tuple[str, str]:
    """Classify an exception into a user-friendly category and message."""
    exc_lower = (type(exc).__name__ + " " + str(exc)).lower()

    # Anti-silent-fallback boundary (memory_store._construct_store): the
    # RuntimeError text embeds the raw psycopg error, which otherwise
    # collides with the generic "connection refused"/"operationalerror"
    # keywords below and would get reclassified into the generic
    # database_not_connected setup guide — silently discarding the far
    # more load-bearing message that a production DATABASE_URL was
    # explicitly configured and refused to fall back to SQLite. Must be
    # checked before the generic keyword scan.
    if "explicit database_url unreachable" in exc_lower:
        return "explicit_database_url_unreachable", str(exc)

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
        except RuntimeError:
            # Loop still running (handler leaked a task); the thread-local
            # loop is abandoned and reclaimed at interpreter exit.
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
    On any exception: logs the exception (type + full traceback) then
    raises ``fastmcp.exceptions.ToolError`` carrying the classified,
    user-friendly message (DB errors get the setup guide; everything
    else gets ``<ExceptionType>: <message>``, no traceback). Never
    returns an error dict -- see the module docstring for why a dict
    return on this path silently fails FastMCP's outputSchema check.
    """
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
        # Log BEFORE classification: classification only keeps a
        # user-friendly message, discarding the traceback. Without this,
        # the underlying failure (e.g. a real bug in the handler body,
        # as opposed to a DB-not-configured condition) is unrecoverable
        # from server logs -- the diagnosticability gap that motivated
        # this fix.
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
            # NOT ``as exc``: rebinding the outer ``exc`` here would unbind
            # it when this handler exits, breaking ``raise ... from exc``.
            except Exception as metrics_exc:  # noqa: BLE001 — metrics must never mask the tool error
                logger.debug("error-counter increment failed: %s", metrics_exc)
        # issue #147: this used to append the DATABASE_URL hint to EVERY
        # unclassified exception type (FileNotFoundError, ValueError, ...),
        # not just DB-related ones -- misleading a user chasing a genuine
        # filesystem/logic bug into "checking PostgreSQL" when it was
        # demonstrably healthy. The two DB-specific categories already
        # carry their own actionable guide as `message` itself
        # (`_EXTENSION_GUIDE` / `_DB_SETUP_GUIDE`); a generic, unclassified
        # exception gets no DB hint at all.
        full_message = f"{error_type}: {message}"
        raise ToolError(full_message) from exc
