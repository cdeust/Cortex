"""Friendly error handling for MCP tool calls.

Wraps handler exceptions so users never see raw Python tracebacks.
Database connection errors get a helpful setup guide instead.

Phase 5 adds two transparent safety nets on top of error handling:
  * per-tool admission semaphore (Phase 5 step 5)
  * asyncio.to_thread offload so handler bodies (which call sync
    DB methods) run on a worker thread instead of blocking the event
    loop

HC-CORTEX-002 adds a transaction-finalization boundary around every handler:
unfinished SQLite work is rolled back on failure, while apparent success with
an open transaction is rejected instead of emitting a false acknowledgement.
Registered PostgreSQL MCP tools already used the named offload path and retain
that behavior; unnamed compatibility calls now use the same offload boundary.

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
Fix: raise ``mcp.server.mcpserver.exceptions.ToolError`` instead of
returning the error dict (was ``fastmcp.exceptions.ToolError`` before
the mcp 2.0.0 migration -- same name, same family, mcp 2.0.0 folded
FastMCP's tool-call machinery into the SDK itself). The MCPServer
``call_tool`` dispatch re-raises a ``ToolError`` unchanged (no
re-wrapping), and the low-level MCP server's ``call_tool`` handler
builds the ``isError=True`` result from ``str(exc)`` directly -- BEFORE
any outputSchema check, which only runs on the non-error branch.
Raising therefore reaches the client with the classified message intact.

Usage in tool registries:
    from mcp_server.tool_error_handler import safe_handler

    async def tool_remember(...) -> dict:
        result = await safe_handler(remember.handler, {...}, tool_name="remember")
        return result
"""

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

# Connection/auth failures ONLY — each phrase below is unambiguous about a
# server that is unreachable, still starting, or refusing credentials.
#
# Deliberately NOT here (issue: SQLite query errors masked as
# "PostgreSQL not connected"): the exception CLASS name "operationalerror",
# a bare "does not exist", a bare "role", and a bare "timeout". Those match
# ordinary query-level failures — a FTS5 "syntax error", "no such table",
# a column that "does not exist", a statement/lock "timeout" — none of
# which are connection problems. On the SQLite backend they are never
# connection problems, yet the base class ``sqlite3.OperationalError`` set
# ``type(exc).__name__.lower() == "operationalerror"`` and every one of
# them got the PostgreSQL ``brew install`` guide, burying the real error
# (a FTS5 syntax error in get_causal_chain surfaced exactly this way).
# An error that is genuinely a create-db/create-role setup step is still
# fully actionable from its own honest ``OperationalError: ... FATAL:
# database "cortex" does not exist`` text, which the fall-through returns.
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

    Each worker thread gets its own event loop; no cross-thread loop
    sharing. The loop is closed at the end so thread reuse doesn't
    carry over state.
    """
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

    Every handler runs on a worker thread via ``asyncio.to_thread``. When
    ``tool_name`` is provided:
      * The call is gated by the per-tool admission semaphore (Phase 5
        step 5). Bounds concurrency so one client cannot DoS a tool by
        hammering it.
      * Duration and outcome metrics include the tool name.

    When ``tool_name`` is omitted, admission and named metrics remain disabled,
    but offload and transaction isolation are preserved. This keeps concurrent
    compatibility calls from sharing the event-loop thread's SQLite handle.

    Contract (issue #17 — Liskov enforcement across all MCP handlers):
      precondition: ``handler_fn`` is an async callable returning a dict.
      postcondition: returns a ``dict[str, Any]``. Never a JSON string.
                     The MCP SDK validates structured content against
                     the declared ``output_schema`` and rejects strings.
                     Under mcp 2.0.0 the tool-registration function's own
                     return annotation must be ``dict[str, Any]`` (not
                     bare ``dict``) for structured content to populate at
                     all — see ``mcp_server/handlers/_tool_meta.py::
                     apply_output_schemas``'s docstring.

    On success: returns the handler's dict verbatim.
    On any exception: logs the exception (type + full traceback) then
    raises ``mcp.server.mcpserver.exceptions.ToolError`` carrying the classified,
    user-friendly message (DB errors get the setup guide; everything
    else gets ``<ExceptionType>: <message>``, no traceback). Never
    returns an error dict -- see the module docstring for why a dict
    return on this path silently fails the MCP SDK's outputSchema check.
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
            result = await asyncio.to_thread(_run_coroutine_on_thread, handler_fn, args)
        # Defensive: every handler must already return a dict per its
        # ``output_schema``. If a handler regresses to None we surface
        # an empty dict so the MCP SDK's structured-content validator
        # does not reject the response.
        if result is None:
            return {}
        # Single wire format across backends. The PG store returns
        # ``datetime``/``numpy`` scalars where the SQLite store returns
        # ``str``/``float``; the MCP SDK can only build ``structuredContent``
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
