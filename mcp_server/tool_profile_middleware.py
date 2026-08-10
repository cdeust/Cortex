"""MCP-SDK middleware enforcing the active tool profile (issue #177).

One place decides what a session sees and what it may run:

- ``tools/list`` — filters the advertised tool set to the profile's
  allowed tools (hides the rest).
- ``tools/call`` — REJECTS a call to a tool the profile excludes. Hiding a
  tool from ``tools/list`` while still executing it on call is a security
  hole, not a token optimisation (#177 criterion 5): destructive tools
  (``forget``, ``wiki_purge``, ``wiki_migrate``, delete-class) must be gated,
  not merely hidden. Filtering the list AND gating the call closes both.
- ``prompts/list`` / ``prompts/get`` — the same rule for prompts: a
  prompt is offered only when the profile registers every tool its workflow
  drives (see ``mcp_prompts.required_tools``).

Under the default ``full`` profile every hook is a pass-through, so existing
behaviour is unchanged — the middleware only bites under ``lean``.

Why middleware and not conditional registration: registration stays in the
seven ``tool_registry_*`` modules untouched, and profile membership lives in
exactly one place (``tool_profiles`` + ``mcp_prompts``). Adding a tool never
requires editing profile code (§1.2 / #177 non-goal).

## mcp 2.0.0 migration (was fastmcp.server.middleware.Middleware)

FastMCP's ``Middleware`` had one hook per method
(``on_list_tools``/``on_call_tool``/``on_list_prompts``/``on_get_prompt``).
mcp 2.0.0 replaced it with ``mcp.server.context.ServerMiddleware``: a single
generic hook, ``__call__(ctx, call_next)``, invoked for EVERY JSON-RPC
method (dispatch by ``ctx.method: str``), running BEFORE params validation.
There is no per-method-type interface — this class dispatches on
``ctx.method`` itself to reproduce the four old hooks.

Two behavior-preserving details verified empirically (isolated venv,
mcp==2.0.0, 2026-08-10 — not assumed from the type signatures alone):

1. ``call_next(ctx)``'s return value (``HandlerResult = BaseModel | dict |
   None``) arrives as a **plain dict** for list methods over the in-process
   transport ``mcp.Client(MCPServer)`` uses, but as a **live pydantic
   object** in other paths — both shapes are handled below rather than
   assuming one.
2. Raising an exception from BEFORE ``call_next`` (mirroring the old
   ``raise NotFoundError(...)``/``raise PromptError(...)``) does NOT
   reproduce the old graceful behavior for ``tools/call``: it skips
   ``MCPServer._handle_call_tool``'s own ``except Exception -> isError=True``
   conversion entirely (that conversion lives INSIDE the handler this
   middleware wraps, not in the generic dispatch boundary this middleware
   runs at) and instead surfaces to the client as a bare
   ``MCPError: Internal server error`` with the classified message lost.
   The fix used below: construct and RETURN a
   ``types.CallToolResult(is_error=True, ...)`` directly (short-circuit,
   never call ``call_next``) — ``Extension.intercept_tool_call``'s own
   docstring names this as the supported way to short-circuit. For
   ``prompts/get`` there is no in-band error shape (``GetPromptResult`` has
   no ``isError`` field), so that path still raises — but as
   ``mcp.shared.exceptions.MCPError`` specifically, the one exception class
   ``handler_exception_to_error_data`` recognizes and turns into a clean
   ``ErrorData`` on the wire instead of the generic ``code=0``/
   ``str(e)`` catch-all every other exception type falls through to.

FastMCP owned the ``tools/list`` response envelope: ``on_list_tools``
returned a ``Sequence[Tool]`` and could not set ``nextCursor``. Empirically
(FastMCP 3.2.4, and unchanged in the mcp 2.0.0 rewrite this middleware now
runs on top of) the framework returns the full allowed set in a single page
with no cursor — which is exactly #177 criterion 4's mandated absent-cursor
behaviour ("returns the full allowed set — the one that cannot break
existing clients"). We do not fork the SDK's protocol layer to synthesise a
cursor; the per-session token win comes from the profile filter reducing
that set, and is measured in ``benchmarks/mcp_profile_tokens.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, TextContent

from mcp_server import mcp_prompts, tool_profiles
from mcp_server.tool_profiles import ToolProfile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server.context import CallNext, ServerRequestContext


def _filter_named_list(
    result: Any, *, list_key: str, keep: Callable[[str], bool]
) -> Any:
    """Drop entries whose ``name`` fails ``keep``, from either result shape.

    ``result`` is a ``types.ListToolsResult``/``types.ListPromptsResult``
    (has a ``.model_copy`` + the named attribute) or the equivalent plain
    dict (same key name — mcp 2.0.0's own field name, see this module's
    docstring). Anything else is returned unchanged: a filter that cannot
    recognize its input must not silently drop it.
    """
    if hasattr(result, "model_copy") and hasattr(result, list_key):
        items = getattr(result, list_key)
        kept = [item for item in items if keep(item.name)]
        return result.model_copy(update={list_key: kept})
    if isinstance(result, dict) and list_key in result:
        updated = dict(result)
        updated[list_key] = [
            item for item in result[list_key] if keep(item.get("name"))
        ]
        return updated
    return result


def _requested_name(ctx: "ServerRequestContext[Any, Any]") -> str:
    """The ``params.name`` a gated request asks for, as a string.

    ``params`` is untyped off the wire, so a missing or non-string ``name``
    is a malformed request. It collapses to ``""``, which no profile lists
    and every gate below therefore refuses -- the same outcome an unknown
    name already got, now with a type the predicates accept.
    """
    name = (ctx.params or {}).get("name")
    return name if isinstance(name, str) else ""


class ToolProfileMiddleware:
    """Enforces ``profile`` over the tool and prompt surfaces.

    A ``mcp.server.context.ServerMiddleware`` (structural protocol, not a
    base class — no ``super().__init__`` to call). Registered via
    ``MCPServer(middleware=[ToolProfileMiddleware(profile)])`` at
    construction time; there is no post-construction ``add_middleware``.
    """

    def __init__(self, profile: ToolProfile) -> None:
        self.profile = profile

    async def __call__(
        self, ctx: "ServerRequestContext[Any, Any]", call_next: "CallNext"
    ) -> Any:
        if self.profile is ToolProfile.FULL:
            return await call_next(ctx)

        if ctx.method == "tools/call":
            return await self._gate_tool_call(ctx, call_next)
        if ctx.method == "prompts/get":
            return await self._gate_prompt_get(ctx, call_next)

        result = await call_next(ctx)
        if ctx.method == "tools/list":
            return _filter_named_list(
                result,
                list_key="tools",
                keep=lambda name: tool_profiles.allows(self.profile, name),
            )
        if ctx.method == "prompts/list":
            return _filter_named_list(
                result,
                list_key="prompts",
                keep=lambda name: mcp_prompts.is_available(name, self.profile),
            )
        return result

    async def _gate_tool_call(
        self, ctx: "ServerRequestContext[Any, Any]", call_next: "CallNext"
    ) -> Any:
        name = _requested_name(ctx)
        if tool_profiles.allows(self.profile, name):
            return await call_next(ctx)
        # Excluded tools look exactly like unregistered ones — the profile
        # IS the registry. This is the security gate: a destructive tool
        # excluded from the profile is rejected here even though it is a
        # registered handler. Returned, not raised: see module docstring
        # point 2 for why raising here loses the message.
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=(
                        f"Unknown tool: {name} (not registered under the "
                        f"'{self.profile.value}' profile; restart with "
                        "--profile full to expose every tool)"
                    ),
                )
            ],
            is_error=True,
        )

    async def _gate_prompt_get(
        self, ctx: "ServerRequestContext[Any, Any]", call_next: "CallNext"
    ) -> Any:
        name = _requested_name(ctx)
        if mcp_prompts.is_available(name, self.profile):
            return await call_next(ctx)
        raise MCPError(
            code=INVALID_PARAMS,
            message=(
                f"Unknown prompt: {name} (not available under the "
                f"'{self.profile.value}' profile; restart with --profile "
                "full to expose every prompt)"
            ),
        )
