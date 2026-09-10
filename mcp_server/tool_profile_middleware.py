"""source: ADR-0692"""

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

    source: ADR-0692"""
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
        # source: ADR-0692

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
