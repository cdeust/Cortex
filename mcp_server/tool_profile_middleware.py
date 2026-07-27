"""FastMCP middleware enforcing the active tool profile (issue #177).

One place decides what a session sees and what it may run:

- ``on_list_tools`` — filters the advertised tool set to the profile's
  allowed tools (hides the rest).
- ``on_call_tool`` — REJECTS a call to a tool the profile excludes. Hiding a
  tool from ``tools/list`` while still executing it on call is a security
  hole, not a token optimisation (#177 criterion 5): destructive tools
  (``forget``, ``wiki_purge``, ``wiki_migrate``, delete-class) must be gated,
  not merely hidden. Filtering the list AND gating the call closes both.
- ``on_list_prompts`` / ``on_get_prompt`` — the same rule for prompts: a
  prompt is offered only when the profile registers every tool its workflow
  drives (see ``mcp_prompts.required_tools``).

Under the default ``full`` profile every hook is a pass-through, so existing
behaviour is unchanged — the middleware only bites under ``lean``.

Why middleware and not conditional registration: registration stays in the
seven ``tool_registry_*`` modules untouched, and profile membership lives in
exactly one place (``tool_profiles`` + ``mcp_prompts``). Adding a tool never
requires editing profile code (§1.2 / #177 non-goal).

FastMCP owns the ``tools/list`` response envelope: ``on_list_tools`` returns a
``Sequence[Tool]`` and cannot set ``nextCursor``. Empirically (FastMCP 3.2.4)
the framework returns the full allowed set in a single page with no cursor —
which is exactly #177 criterion 4's mandated absent-cursor behaviour ("returns
the full allowed set — the one that cannot break existing clients"). We do not
fork FastMCP's protocol layer to synthesise a cursor; the per-session token
win comes from the profile filter reducing that set, and is measured in
``benchmarks/mcp_profile_tokens.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from fastmcp.exceptions import NotFoundError, PromptError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from mcp_server import mcp_prompts, tool_profiles
from mcp_server.tool_profiles import ToolProfile

if TYPE_CHECKING:  # pragma: no cover - typing only
    import mcp.types as mt
    from fastmcp.prompts import Prompt
    from fastmcp.tools import Tool, ToolResult


class ToolProfileMiddleware(Middleware):
    """Enforces ``profile`` over the tool and prompt surfaces."""

    def __init__(self, profile: ToolProfile) -> None:
        self.profile = profile

    # ── Tools ───────────────────────────────────────────────────────────
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next,
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        if self.profile is ToolProfile.FULL:
            return tools
        return [t for t in tools if tool_profiles.allows(self.profile, t.name)]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next,
    ) -> ToolResult:
        name = context.message.name
        if not tool_profiles.allows(self.profile, name):
            # Excluded tools look exactly like unregistered ones — the profile
            # IS the registry. This is the security gate: a destructive tool
            # excluded from the profile is rejected here even though it is a
            # registered handler.
            raise NotFoundError(
                f"Unknown tool: {name} (not registered under the "
                f"'{self.profile.value}' profile; restart with --profile full "
                f"to expose every tool)"
            )
        return await call_next(context)

    # ── Prompts ─────────────────────────────────────────────────────────
    async def on_list_prompts(
        self,
        context: MiddlewareContext[mt.ListPromptsRequest],
        call_next,
    ) -> Sequence[Prompt]:
        prompts = await call_next(context)
        if self.profile is ToolProfile.FULL:
            return prompts
        return [p for p in prompts if mcp_prompts.is_available(p.name, self.profile)]

    async def on_get_prompt(
        self,
        context: MiddlewareContext[mt.GetPromptRequestParams],
        call_next,
    ):
        name = context.message.name
        if not mcp_prompts.is_available(name, self.profile):
            raise PromptError(
                f"Unknown prompt: {name} (not available under the "
                f"'{self.profile.value}' profile; restart with --profile full "
                f"to expose every prompt)"
            )
        return await call_next(context)
