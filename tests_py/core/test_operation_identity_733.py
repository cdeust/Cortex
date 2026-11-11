"""One MCP tool call gives every sample it causes the same operation identity.

Issue #733, slice 3: nested handler samples, worker threads and work that
outlives the call were joined only by ``op`` and ``ts``.
"""

from __future__ import annotations

import asyncio
import json
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from mcp_server.core import telemetry
from mcp_server.telemetry_middleware import TelemetryMiddleware


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.set_exporter(None)
    telemetry.reset()
    yield path
    telemetry.reset()


def _samples(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _tool_call(call_next, name="outer"):
    context = SimpleNamespace(method="tools/call", params={"name": name})
    return asyncio.run(TelemetryMiddleware()(context, call_next))


def test_nested_and_outer_samples_share_one_operation(telemetry_log):
    async def call_next(ctx):
        telemetry.record("nested", latency_ms=1)
        telemetry.record("outer", latency_ms=2)
        return {"content": []}

    _tool_call(call_next)
    nested, outer = _samples(telemetry_log)
    assert outer["operation_id"] is not None
    assert nested["operation_id"] == outer["operation_id"]


def test_two_tool_calls_get_distinct_operations(telemetry_log):
    async def call_next(ctx):
        telemetry.record("outer", latency_ms=1)
        return {"content": []}

    _tool_call(call_next)
    _tool_call(call_next)
    first, second = _samples(telemetry_log)
    assert first["operation_id"] != second["operation_id"]


def test_worker_thread_and_late_work_keep_the_caller_operation(telemetry_log):
    late = []

    async def call_next(ctx):
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool,
                copy_context().run,
                partial(telemetry.record, "worker", latency_ms=1),
            )
        late.append(copy_context())
        telemetry.record("outer", latency_ms=2)
        return {"content": []}

    _tool_call(call_next)
    late[0].run(telemetry.record, "after_call", latency_ms=3)
    by_op = {sample["op"]: sample for sample in _samples(telemetry_log)}
    assert set(by_op) == {"worker", "outer", "after_call"}
    assert len({sample["operation_id"] for sample in by_op.values()}) == 1


def test_sample_outside_a_tool_call_has_no_operation(telemetry_log):
    async def call_next(ctx):
        telemetry.record("outer", latency_ms=1)
        return {"content": []}

    _tool_call(call_next)
    telemetry.record("hook", latency_ms=1)
    assert _samples(telemetry_log)[-1]["operation_id"] is None


def _begin_then_record(*ops):
    telemetry.begin_operation()
    for op in ops:
        telemetry.record(op, latency_ms=1)


def test_a_begun_operation_gives_its_later_samples_one_fresh_id(telemetry_log):
    copy_context().run(_begin_then_record, "store", "report")
    store, report = _samples(telemetry_log)
    assert len(store["operation_id"]) == 32
    assert int(store["operation_id"], 16) >= 0
    assert report["operation_id"] == store["operation_id"]


def test_each_begun_operation_replaces_the_one_before_it(telemetry_log):
    def two_units():
        _begin_then_record("first")
        _begin_then_record("second")

    copy_context().run(two_units)
    first, second = _samples(telemetry_log)
    assert None not in (first["operation_id"], second["operation_id"])
    assert first["operation_id"] != second["operation_id"]


def test_a_begun_operation_ends_with_its_context(telemetry_log):
    copy_context().run(_begin_then_record, "inside")
    telemetry.record("outside", latency_ms=1)
    assert _samples(telemetry_log)[-1]["operation_id"] is None
