"""``check_setup`` and ``get_grooming_health`` record one sample per call (#733).

Before, both tools were registered without ``instrument``: their wall time,
bytes and outcome were absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.doctor import Check
from mcp_server.handlers import check_setup, get_grooming_health


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


def _three_checks(monkeypatch) -> None:
    checks = [
        lambda: Check("a", True, detail="", fix=""),
        lambda: Check("b", False, detail="", fix="fix b"),
        lambda: Check("c", False, detail="", fix="", optional=True),
    ]
    monkeypatch.setattr(check_setup, "active_checks", lambda: checks)


def test_check_setup_records_one_sample_counting_its_checks(telemetry_log, monkeypatch):
    _three_checks(monkeypatch)

    response = asyncio.run(check_setup.handler({}))

    [sample] = _samples(telemetry_log, "check_setup")
    assert response["fixes_needed"] == 1
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["result_count"] == 3
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()["check_setup"]["count"] == 1


def _fake_grooming(monkeypatch) -> None:
    ages = {"wiki": None, "distillation": None, "promotion": None}
    store = SimpleNamespace(get_grooming_ages=lambda: ages)
    monkeypatch.setattr(get_grooming_health, "get_shared_store", lambda: store)
    monkeypatch.setattr(
        get_grooming_health, "_count_promotion_candidates", lambda _s: 2
    )

    async def planner(_args):
        return {"total_clusters_eligible": 4, "total_dossiers_eligible": 5}

    monkeypatch.setattr(get_grooming_health.curate_wiki, "handler", planner)
    monkeypatch.setattr(get_grooming_health.curate_distill, "handler", planner)


def test_get_grooming_health_records_one_sample(telemetry_log, monkeypatch):
    _fake_grooming(monkeypatch)

    response = asyncio.run(get_grooming_health.handler({}))

    [sample] = _samples(telemetry_log, "get_grooming_health")
    assert response["kinds"]["promotion"]["backlog_count"] == 2
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, monkeypatch):
    def broken():
        raise RuntimeError("fixture: store unreachable")

    monkeypatch.setattr(get_grooming_health, "get_shared_store", broken)
    with pytest.raises(RuntimeError, match="store unreachable"):
        asyncio.run(get_grooming_health.handler({}))

    [sample] = _samples(telemetry_log, "get_grooming_health")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(
    telemetry_log, monkeypatch
):
    _three_checks(monkeypatch)

    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await check_setup.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "check_setup"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "check_setup") == []
