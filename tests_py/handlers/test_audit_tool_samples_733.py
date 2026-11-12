"""Three audit tools record one telemetry sample per call (#733).

Before, ``assess_coverage``, ``detect_gaps`` and ``lesson_promotion`` were
registered without ``instrument``: their wall time, bytes and outcome were
absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink. The memory store is
replaced by a double: the tests are about the sample, not the audits, which
``test_assess_coverage.py``, ``test_detect_gaps_contract.py`` and
``test_lesson_promotion.py`` cover.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import assess_coverage, detect_gaps, lesson_promotion

_CANDIDATE = {
    "id": 7,
    "content_preview": "boost lessons in the recall pipeline",
    "tags": ["lesson"],
    "useful_count": 2,
    "access_count": 5,
    "domain": "cortex",
}


class _Store:
    """Answers the reads these handlers make: no memory, one isolated entity."""

    _conn = object()

    def get_all_memories_for_validation(self, **_kwargs) -> list[dict]:
        return []

    def get_isolated_entities(self, **_kwargs) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [{"id": 3, "name": "orphan", "type": "function", "created_at": now}]

    def count_memories(self) -> dict:
        return {"total": 0}

    def get_domain_entity_counts(self) -> list[dict]:
        return []


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
    monkeypatch.setattr(assess_coverage, "_get_store", lambda: double)
    monkeypatch.setattr(detect_gaps, "_get_store", lambda: double)
    monkeypatch.setattr(detect_gaps, "load_profiles", lambda: {})
    monkeypatch.setattr(lesson_promotion, "get_shared_store", lambda: double)
    monkeypatch.setattr(
        lesson_promotion,
        "list_lesson_promotion_candidates",
        lambda _conn, limit: [dict(_CANDIDATE)],
    )
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


def test_assess_coverage_records_one_sample(telemetry_log, store):
    response = asyncio.run(assess_coverage.handler({}))

    assert response["total_memories"] == 0
    _one_ok_sample(telemetry_log, "assess_coverage", response)


def test_detect_gaps_records_one_sample_counting_gaps(telemetry_log, store):
    response = asyncio.run(detect_gaps.handler({}))

    assert response["total_gaps"] == 1
    sample = _one_ok_sample(telemetry_log, "detect_gaps", response)
    assert sample["result_count"] == 1


def test_lesson_promotion_records_one_sample_counting_jobs(telemetry_log, store):
    response = asyncio.run(lesson_promotion.handler({"limit": 5}))

    assert response["returned"] == 1
    sample = _one_ok_sample(telemetry_log, "lesson_promotion", response)
    assert sample["result_count"] == 1


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, store):
    with pytest.raises(ValueError, match="invalid literal"):
        asyncio.run(assess_coverage.handler({"stale_days": "soon"}))

    [sample] = _samples(telemetry_log, "assess_coverage")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, store):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await detect_gaps.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "detect_gaps"]
    assert sample["operation_id"]
