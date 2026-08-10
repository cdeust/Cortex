"""Tests for mcp_server.handlers.get_telemetry — Popper C6 telemetry.

Issue #17 (PSGSupport): pin the handler-return-shape contract. The MCP
SDK enforces ``output_schema`` and rejects strings. The handler — and
``safe_handler`` around it — must return a dict.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers.get_telemetry import handler


class TestGetTelemetryReturnsDict:
    """Liskov: get_telemetry must return a dict per its output_schema."""

    def test_handler_direct_returns_dict(self):
        result = asyncio.run(handler())
        assert isinstance(result, dict)

    def test_handler_includes_required_fields(self):
        result = asyncio.run(handler())
        # Per the schema: counters + ratio_reads_writes are required.
        assert "counters" in result
        assert "ratio_reads_writes" in result

    def test_safe_handler_returns_dict(self):
        from mcp_server.tool_error_handler import safe_handler

        result = asyncio.run(safe_handler(handler, {}, tool_name="get_telemetry"))
        assert isinstance(result, dict)
        assert not isinstance(result, str)


@pytest.mark.asyncio
async def test_handler_async_returns_dict():
    """Direct async path also returns a dict (not a coroutine of str)."""
    result = await handler()
    assert isinstance(result, dict)
