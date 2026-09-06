"""Measure real MCP success/error TextContent once, including worker offload."""

from __future__ import annotations

import asyncio
import json
from contextvars import copy_context
from types import SimpleNamespace

import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from mcp_server.core import telemetry
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.shared.telemetry_context import count_reranked, set_retrieval_tier
from mcp_server.telemetry_middleware import TelemetryMiddleware
from mcp_server.tool_error_handler import safe_handler


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.set_exporter(None)
    telemetry.reset()
    yield path
    telemetry.reset()
    telemetry.set_exporter(None)


def _samples(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _server(*, fail=False, invalid_output=False, measured=True):
    server = MCPServer(name="telemetry-fixture", middleware=[TelemetryMiddleware()])

    async def handler(args):
        set_retrieval_tier("pg")
        count_reranked(2)
        if fail:
            raise ValueError("échec de fixture 🧠")
        return {"message": "café 🧠"}

    observed = instrument("fixture", handler) if measured else handler

    @server.tool(name="fixture")
    async def fixture() -> dict[str, str]:
        return await safe_handler(observed, {})

    if invalid_output:
        tool = server._tool_manager.get_tool("fixture")
        assert tool is not None

        # The SDK validates this model after the instrumented handler returns.
        class RequiredOutput(BaseModel):
            required_field: int

        tool.fn_metadata.output_model = RequiredOutput
    return server


def _call(server):
    async def run():
        async with Client(server) as client:
            return await client.call_tool("fixture", {})

    return asyncio.run(run())


@pytest.mark.parametrize(
    "fail,invalid_output", [(False, False), (True, False), (False, True)]
)
def test_sdk_text_response_is_counted_exactly_once(fail, invalid_output, telemetry_log):
    result = _call(_server(fail=fail, invalid_output=invalid_output))
    samples = _samples(telemetry_log)
    assert len(samples) == 1
    sample = samples[0]
    text = [block.text for block in result.content if isinstance(block, TextContent)]
    assert sample["bytes_out"] == sum(len(value.encode("utf-8")) for value in text) > 0
    assert sample["ok"] is (not result.is_error)
    assert result.is_error is (fail or invalid_output)
    if fail:
        assert "échec de fixture 🧠" in "".join(text)
    elif not invalid_output:
        assert json.loads("".join(text)) == {"message": "café 🧠"}
    assert sample["tier"] == "pg"
    assert sample["reranked_count"] == 2
    counters = telemetry.snapshot()["fixture"]
    assert counters["count"] == 1
    assert counters["bytes_out"] == sample["bytes_out"]
    assert counters["fail"] == int(result.is_error)


def test_uninstrumented_sdk_tool_creates_no_sample(telemetry_log):
    result = _call(_server(measured=False))
    assert not result.is_error
    assert not telemetry_log.exists()
    assert telemetry.snapshot() == {}


@pytest.mark.parametrize("as_dict", [False, True])
def test_middleware_preserves_response_and_nested_operation(as_dict, telemetry_log):
    response = CallToolResult(
        content=[TextContent(type="text", text="réponse 🧠")], is_error=True
    )
    expected = response.model_dump(by_alias=True) if as_dict else response

    async def call_next(ctx):
        telemetry.record("nested", latency_ms=1, bytes_out=5)
        telemetry.record("fixture", latency_ms=2, bytes_out=0)
        assert telemetry.snapshot() == {}
        assert not telemetry_log.exists()
        return expected

    context = SimpleNamespace(method="tools/call", params={"name": "fixture"})
    result = asyncio.run(TelemetryMiddleware()(context, call_next))
    assert result is expected
    nested, outer = _samples(telemetry_log)
    assert nested["bytes_out"] == 5
    assert nested["ok"] is True
    assert outer["bytes_out"] == len("réponse 🧠".encode("utf-8"))
    assert outer["ok"] is False


def test_missing_response_publishes_failure_without_swallowing_it(telemetry_log):
    failure = RuntimeError("transport fixture failure")

    async def call_next(ctx):
        telemetry.record("fixture", latency_ms=1, ok=False)
        raise failure

    context = SimpleNamespace(method="tools/call", params={"name": "fixture"})
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(TelemetryMiddleware()(context, call_next))
    assert caught.value is failure
    sample = _samples(telemetry_log)
    assert len(sample) == 1
    assert sample[0]["bytes_out"] == 0
    assert sample[0]["ok"] is False


def test_capture_restores_context_and_late_worker_can_publish(telemetry_log):
    with telemetry.capture_records() as samples:
        worker_context = copy_context()
        telemetry.record("captured", latency_ms=1.23456)
        assert telemetry.snapshot() == {}
    assert not telemetry_log.exists()
    telemetry.publish_record(samples[0])
    worker_context.run(telemetry.record, "late_worker", latency_ms=2)
    telemetry.record("direct", latency_ms=3)
    assert [sample["op"] for sample in _samples(telemetry_log)] == [
        "captured",
        "late_worker",
        "direct",
    ]
    assert len(samples) == 1
    assert telemetry.snapshot()["captured"]["latency_ms_sum"] == 1.23456
