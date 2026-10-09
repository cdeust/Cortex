"""Capture outcomes reach telemetry as distinct operations (issue #660).

A declined capture is ``capture_skipped`` with ``skipped=True``; a stalled spool and
the worker's lifecycle faults are errors; a payload that went through the remember
handler is ``capture_processed``. ``check_setup`` reads these to tell a working
capture from a silent one.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.core import telemetry
from mcp_server.hooks import capture_dispatch, capture_store
from tests_py.hooks.test_capture_worker_policy import payload


@pytest.fixture(autouse=True)
def _telemetry(monkeypatch, tmp_path):
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    monkeypatch.setattr(telemetry, "_LOG_PATH", tmp_path / "telemetry.jsonl")
    telemetry.reset()
    yield
    telemetry.reset()


def _counters(op: str) -> tuple[int, int, int]:
    c = telemetry.snapshot()[op]
    return c["ok"], c["fail"], c["skipped"]


def test_a_skipped_capture_is_counted_as_skipped_not_as_an_error() -> None:
    capture_dispatch.report_failure("fixture", 0.0)
    assert _counters("capture_skipped") == (0, 0, 1)


@pytest.mark.parametrize("op", ["capture_spool_stalled", "capture_worker_lifecycle"])
def test_stall_and_lifecycle_faults_stay_errors(op: str) -> None:
    capture_dispatch.report_failure("fixture", 0.0, op)
    assert _counters(op) == (0, 1, 0)


def test_a_stored_payload_is_recorded_as_processed(monkeypatch) -> None:
    async def handler(_payload):
        return {"stored": True, "memory_id": 7}

    monkeypatch.setattr(
        "mcp_server.hooks.post_tool_capture._load_remember", lambda: (None, handler)
    )
    asyncio.run(capture_store.store(payload()))
    assert _counters("capture_processed") == (1, 0, 0)


def test_a_gated_payload_is_also_processed(monkeypatch) -> None:
    async def handler(_payload):
        return {"stored": False, "reason": "below_threshold"}

    monkeypatch.setattr(
        "mcp_server.hooks.post_tool_capture._load_remember", lambda: (None, handler)
    )
    asyncio.run(capture_store.store(payload()))
    assert _counters("capture_processed") == (1, 0, 0)


def test_a_failing_handler_records_no_processed_sample(monkeypatch) -> None:
    async def handler(_payload):
        raise RuntimeError("fixture store failure")

    monkeypatch.setattr(
        "mcp_server.hooks.post_tool_capture._load_remember", lambda: (None, handler)
    )
    with pytest.raises(RuntimeError, match="fixture store failure"):
        asyncio.run(capture_store.store(payload()))
    assert "capture_processed" not in telemetry.snapshot()


def test_a_refused_payload_records_no_processed_sample() -> None:
    with pytest.raises(ValueError):
        asyncio.run(capture_store.store({}))
    assert "capture_processed" not in telemetry.snapshot()
