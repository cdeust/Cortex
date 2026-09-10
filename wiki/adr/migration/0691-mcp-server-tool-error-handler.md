---
title: "ADR-0691 — mcp_server/tool_error_handler.py rationale"
status: accepted
source: mcp_server/tool_error_handler.py
---

# ADR-0691 — mcp_server/tool_error_handler.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Wraps handler exceptions so users never see raw Python tracebacks.
Database connection errors get a helpful setup guide instead.
````

## module — original line 6 (docstring)

````text
Phase 5 adds two transparent safety nets on top of error handling:
  * per-tool admission semaphore (Phase 5 step 5)
  * asyncio.to_thread offload so handler bodies (which call sync
    DB methods) run on a worker thread instead of blocking the event
    loop
````

## module — original line 12 (docstring)

````text
HC-CORTEX-002 adds a transaction-finalization boundary around every handler:
unfinished SQLite work is rolled back on failure, while apparent success with
an open transaction is rejected instead of emitting a false acknowledgement.
Registered PostgreSQL MCP tools already used the named offload path and retain
that behavior; unnamed compatibility calls now use the same offload boundary.
````

## module — original line 18 (docstring)

````text
Issue #17 (PSGSupport): handlers that declare ``output_schema`` were
rejected by FastMCP with ``structured_content must be a dict or None.
Got str: '{...}'`` because this wrapper used to ``json.dumps`` the
result before returning. FastMCP 2.x validates the return shape
against the declared schema and rejects strings. Fix: return the
dict directly. The handler contract IS dict-or-None (Liskov: every
``mcp__cortex__*`` handler now uniformly satisfies the same interface).
````

## module — original line 26 (docstring)

````text
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
````

## module — original line 45 (docstring)

````text
Usage in tool registries:
    from mcp_server.tool_error_handler import safe_handler
````

## module — original line 48 (docstring)

````text
    async def tool_remember(...) -> dict:
        result = await safe_handler(remember.handler, {...}, tool_name="remember")
        return result

````

## _run_coroutine_on_thread — original line 160 (docstring)

````text
    Each worker thread gets its own event loop; no cross-thread loop
    sharing. The loop is closed at the end so thread reuse doesn't
    carry over state.
    
````

## safe_handler — original line 184 (docstring)

````text
    Every handler runs on a worker thread via ``asyncio.to_thread``. When
    ``tool_name`` is provided:
      * The call is gated by the per-tool admission semaphore (Phase 5
        step 5). Bounds concurrency so one client cannot DoS a tool by
        hammering it.
      * Duration and outcome metrics include the tool name.
````

## safe_handler — original line 195 (docstring)

````text
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
````

## safe_handler — original line 206 (docstring)

````text
    On success: returns the handler's dict verbatim.
    On any exception: logs the exception (type + full traceback) then
    raises ``mcp.server.mcpserver.exceptions.ToolError`` carrying the classified,
    user-friendly message (DB errors get the setup guide; everything
    else gets ``<ExceptionType>: <message>``, no traceback). Never
    returns an error dict -- see the module docstring for why a dict
    return on this path silently fails the MCP SDK's outputSchema check.
    
````

## module — original line 96 (comment)

````text
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
````

## module — original line 130 (comment)

````text
# Anti-silent-fallback boundary (memory_store._construct_store): the
# RuntimeError text embeds the raw psycopg error, which otherwise
# collides with the generic "connection refused"/"operationalerror"
# keywords below and would get reclassified into the generic
# database_not_connected setup guide — silently discarding the far
# more load-bearing message that a production DATABASE_URL was
# explicitly configured and refused to fall back to SQLite. Must be
# checked before the generic keyword scan.
````

## module — original line 230 (comment)

````text
# Defensive: every handler must already return a dict per its
# ``output_schema``. If a handler regresses to None we surface
# an empty dict so the MCP SDK's structured-content validator
# does not reject the response.
````

## module — original line 236 (comment)

````text
# Single wire format across backends. The PG store returns
# ``datetime``/``numpy`` scalars where the SQLite store returns
# ``str``/``float``; the MCP SDK can only build ``structuredContent``
# from JSON-native values, so a non-native field silently drops
# structuredContent and the client rejects the call ("outputSchema
# defined but no structured output returned"). Normalizing here —
# the one boundary every handler crosses — guarantees an identical,
# schema-friendly return shape regardless of which backend produced
# it. Native dicts (e.g. remember) pass through unchanged.
````

## module — original line 247 (comment)

````text
# Log BEFORE classification: classification only keeps a
# user-friendly message, discarding the traceback. Without this,
# the underlying failure (e.g. a real bug in the handler body,
# as opposed to a DB-not-configured condition) is unrecoverable
# from server logs -- the diagnosticability gap that motivated
# this fix.
````

## module — original line 265 (comment)

````text
# NOT ``as exc``: rebinding the outer ``exc`` here would unbind
# it when this handler exits, breaking ``raise ... from exc``.
````

## inline — original line 267 (directive-rationale)

````text
# noqa: BLE001 — metrics must never mask the tool error
````

## module — original line 269 (comment)

````text
# issue #147: this used to append the DATABASE_URL hint to EVERY
# unclassified exception type (FileNotFoundError, ValueError, ...),
# not just DB-related ones -- misleading a user chasing a genuine
# filesystem/logic bug into "checking PostgreSQL" when it was
# demonstrably healthy. The two DB-specific categories already
# carry their own actionable guide as `message` itself
# (`_EXTENSION_GUIDE` / `_DB_SETUP_GUIDE`); a generic, unclassified
# exception gets no DB hint at all.
````
