"""consolidate records one telemetry sample per call (issue #733, slice 3).

Before, ``consolidate`` was registered without ``instrument``: its wall time,
bytes and outcome were absent from ``get_telemetry`` and the JSONL. These tests
drive the registered ``handler`` on the test store and read the JSONL sink.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import consolidate

# Every optional cycle off: the always-run cycles still execute on the store.
_QUIET = {"decay": False, "compress": False, "cls": False, "memify": False}
_ARGS = {**_QUIET, "deep": False, "wiki": False}


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


def _consolidate_samples(path) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == "consolidate"]


def test_a_call_records_one_sample_with_its_bytes(telemetry_log):
    response = asyncio.run(consolidate.handler(_ARGS))

    [sample] = _consolidate_samples(telemetry_log)
    assert sample["ok"] is True
    assert sample["skipped"] is False
    assert sample["latency_ms"] >= response["duration_ms"]
    assert sample["bytes_in"] == len(json.dumps(_ARGS).encode("utf-8"))
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()["consolidate"]["count"] == 1


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("fixture: store unreachable")

    monkeypatch.setattr(consolidate, "_run_cycles", broken)
    with pytest.raises(RuntimeError, match="store unreachable"):
        asyncio.run(consolidate.handler(_ARGS))

    [sample] = _consolidate_samples(telemetry_log)
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await consolidate.handler(_ARGS)
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "consolidate"]
    assert sample["operation_id"]
    assert _consolidate_samples(telemetry_log) == []
