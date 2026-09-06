"""Finalize existing operation samples from the MCP SDK's actual text response.

The SDK converts handler exceptions to TextContent inside call_next. Measuring
here includes those errors without reconstructing SDK messages or changing tool
results. Source: mcp 2.0.0 MCPServer._handle_call_tool and ServerMiddleware.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

from mcp.types import CallToolResult, TextContent
from typing_extensions import NotRequired

from mcp_server.core import telemetry

if TYPE_CHECKING:
    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext


class _ContentBlock(TypedDict):
    type: str
    text: NotRequired[str]


class _ToolResponse(TypedDict):
    content: list[_ContentBlock]
    isError: NotRequired[bool]


def _response_measurement(result: HandlerResult) -> tuple[int, bool] | None:
    """Support both SDK result shapes without serializing the transport envelope."""
    if isinstance(result, CallToolResult):
        text = (
            block.text for block in result.content if isinstance(block, TextContent)
        )
        return sum(len(value.encode("utf-8")) for value in text), not result.is_error
    if isinstance(result, dict) and "content" in result:
        response = cast("_ToolResponse", result)
        text = (
            block.get("text", "")
            for block in response["content"]
            if block["type"] == "text"
        )
        return sum(len(value.encode("utf-8")) for value in text), not response.get(
            "isError", False
        )
    return None


def _finalize_response(
    samples: list[telemetry.TelemetrySample], name: str, result: HandlerResult
) -> None:
    """Update the outer operation only; nested handler samples retain their scope."""
    measurement = _response_measurement(result)
    if measurement is None:
        return
    for sample in reversed(samples):
        if sample["op"] == name:
            sample["bytes_out"], sample["ok"] = measurement
            return


class TelemetryMiddleware:
    """Publish existing handler samples exactly once, after SDK conversion."""

    async def __call__(
        self, ctx: ServerRequestContext[object, object], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)
        name = (ctx.params or {}).get("name")
        result = None
        samples: list[telemetry.TelemetrySample] = []
        try:
            with telemetry.capture_records() as samples:
                result = await call_next(ctx)
        finally:
            if isinstance(name, str):
                _finalize_response(samples, name, result)
            for sample in samples:
                telemetry.publish_record(sample)
        return result
