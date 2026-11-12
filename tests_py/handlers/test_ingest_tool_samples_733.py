"""Three ingestion tools record one telemetry sample per call (#733).

Before, ``change_impact``, ``ingest_findings`` and ``ingest_prd`` were
registered without ``instrument``: their wall time, bytes and outcome were
absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink. The codebase bridge, the
findings artifacts and the store are replaced by doubles: the tests are about
the sample, not the ingestion, which ``test_change_impact_contract.py``,
``test_ingest_findings.py`` and ``test_ingest_prd.py`` cover.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import change_impact, ingest_findings, ingest_prd


class _Conn:
    def commit(self) -> None:
        return None


class _Bridge:
    async def close(self) -> None:
        return None


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


@pytest.fixture
def impact(monkeypatch):
    async def collect(*_a, **_k):
        return ["f"], ["a.py"]

    match = SimpleNamespace(
        memory_id=1, matched_symbols=["f"], matched_files=[], match_count=1
    )
    store = SimpleNamespace(get_all_memories_for_validation=lambda **_k: [])
    monkeypatch.setattr(change_impact, "is_enabled", lambda: True)
    monkeypatch.setattr(change_impact, "resolve_graph_path", lambda: "/graph")
    monkeypatch.setattr(change_impact, "APBridge", _Bridge)
    monkeypatch.setattr(change_impact, "_collect_impact", collect)
    monkeypatch.setattr(change_impact, "_get_store", lambda: store)
    monkeypatch.setattr(change_impact, "match_memories", lambda **_k: [match] * 2)


@pytest.fixture
def findings(monkeypatch, tmp_path):
    store = SimpleNamespace(_conn=_Conn())
    index = {"findings": {"F1": {}, "F2": {}, "F3": {}}}
    monkeypatch.setattr(ingest_findings, "_get_store", lambda: store)
    monkeypatch.setattr(
        ingest_findings, "resolve_output_dir", lambda *_a, **_k: tmp_path
    )
    monkeypatch.setattr(ingest_findings, "read_index", lambda *_a: index)
    monkeypatch.setattr(ingest_findings, "load_finding", lambda *_a: {})
    monkeypatch.setattr(
        ingest_findings, "write_finding", lambda *_a: {"verified": True}
    )


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


def _one_ok_sample(path, op: str, response: dict) -> dict:
    [sample] = _samples(path, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1
    return sample


def test_change_impact_records_one_sample_counting_matches(telemetry_log, impact):
    response = asyncio.run(change_impact.handler({"base": "HEAD~1"}))

    assert response["status"] == "ok"
    sample = _one_ok_sample(telemetry_log, "change_impact", response)
    assert sample["result_count"] == 2


def test_ingest_findings_records_one_sample_counting_results(telemetry_log, findings):
    response = asyncio.run(ingest_findings.handler({"run_id": "run1"}))

    assert response["findings_total"] == 3
    sample = _one_ok_sample(telemetry_log, "ingest_findings", response)
    assert sample["result_count"] == 3


def test_ingest_prd_records_one_sample(telemetry_log):
    response = asyncio.run(ingest_prd.handler({}))

    assert response["ingested"] is False
    _one_ok_sample(telemetry_log, "ingest_prd", response)


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, monkeypatch):
    async def broken(_args):
        raise RuntimeError("fixture: fetch broke")

    monkeypatch.setattr(ingest_prd, "_fetch_prd", broken)
    with pytest.raises(RuntimeError, match="fetch broke"):
        asyncio.run(ingest_prd.handler({"content": "x"}))

    [sample] = _samples(telemetry_log, "ingest_prd")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, impact):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await change_impact.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "change_impact"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "change_impact") == []
