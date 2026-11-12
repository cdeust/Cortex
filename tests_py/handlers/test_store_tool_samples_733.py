"""Three store tools record one telemetry sample per call (#733).

Before, ``anchor``, ``why`` and ``get_project_story`` were registered without
``instrument``: their wall time, bytes and outcome were absent from
``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink. The memory store is
replaced by a double: the tests are about the sample, not the store, which
``test_why.py``, ``test_project_story_contract.py`` and the GHSA-7848 anchor
tests cover.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import anchor, get_project_story, why

_RECEIPT = {
    "receipt_id": 1,
    "channel": "recall",
    "session_id": None,
    "emitted_at": "2026-07-07T10:00:00+00:00",
    "memory_id": 11,
    "rank": 0,
    "score": 0.9,
    "memory_row_id": 11,
    "content": "alpha",
    "memory_created_at": "2026-07-01T00:00:00+00:00",
    "memory_source": "lesson",
    "memory_domain": "cortex",
    "superseded_by_id": None,
}


class _Store:
    """Answers the three reads these handlers make; no memory exists."""

    def get_memory(self, _memory_id: int) -> None:
        return None

    def fetch_injection_receipts(self, _ids: list[int]) -> list[dict]:
        return [dict(_RECEIPT)]

    def get_hot_memories(self, **_kwargs) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [{"id": 7, "content": "We decided to keep SQLite.", "created_at": now}]


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


@pytest.fixture
def store(monkeypatch):
    double = _Store()
    monkeypatch.setattr(anchor, "_get_store", lambda: double)
    monkeypatch.setattr(get_project_story, "_get_store", lambda: double)
    monkeypatch.setattr(why, "get_shared_store", lambda: double)
    return double


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


def _one_ok_sample(path, op: str, response: dict) -> dict:
    [sample] = _samples(path, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1
    return sample


def test_anchor_records_one_sample(telemetry_log, store):
    response = asyncio.run(anchor.handler({"memory_id": 42}))

    assert response == {"anchored": False, "reason": "memory not found: 42"}
    _one_ok_sample(telemetry_log, "anchor", response)


def test_why_records_one_sample_counting_evidence(telemetry_log, store):
    response = asyncio.run(why.handler({"receipt_ids": [1]}))

    assert response["count"] == 1
    sample = _one_ok_sample(telemetry_log, "why", response)
    assert sample["result_count"] == 1


def test_get_project_story_records_one_sample_counting_chapters(telemetry_log, store):
    response = asyncio.run(get_project_story.handler({"period": "all"}))

    assert len(response["chapters"]) == 1
    sample = _one_ok_sample(telemetry_log, "get_project_story", response)
    assert sample["result_count"] == 1


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, store):
    with pytest.raises(ValueError, match="non-empty list"):
        asyncio.run(why.handler({"receipt_ids": []}))

    [sample] = _samples(telemetry_log, "why")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, store):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await anchor.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "anchor"]
    assert sample["operation_id"]
