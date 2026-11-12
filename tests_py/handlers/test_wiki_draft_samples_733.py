"""The two wiki draft tools record one telemetry sample per call (#733).

Before, ``wiki_get_draft`` and ``wiki_refine_draft`` were registered without
``instrument``: their wall time, bytes and outcome were absent from
``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
the registered ``handler_get`` and ``handler_refine`` and read the JSONL sink.
The store, the draft table and the kind registry are replaced by doubles: the
tests are about the sample, not the draft pipeline, which
``test_wiki_refine_confidence.py`` covers on SQLite.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import wiki_refine

_DRAFT = {
    "id": 7,
    "kind": "explanation",
    "title": "t",
    "lead": "l",
    "memory_id": 1,
    "concept_id": None,
    "confidence": 0.5,
    "synth_model": "fixture",
}


class _Conn:
    def commit(self) -> None:
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
def drafts(monkeypatch):
    store = SimpleNamespace(_conn=_Conn())
    monkeypatch.setattr(wiki_refine, "_get_store", lambda: store)
    monkeypatch.setattr(wiki_refine, "load_registry", lambda _root: None)
    monkeypatch.setattr(wiki_refine, "list_drafts", lambda *_a, **_k: [_DRAFT] * 2)
    monkeypatch.setattr(wiki_refine, "get_draft", lambda _c, _i: dict(_DRAFT))
    monkeypatch.setattr(wiki_refine, "update_draft", lambda *_a, **_k: True)
    monkeypatch.setattr(wiki_refine, "insert_memo", lambda *_a, **_k: None)


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


def _one_ok_sample(path, op: str, response: dict) -> dict:
    [sample] = _samples(path, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1
    return sample


def test_wiki_get_draft_listing_records_one_sample_counting_drafts(
    telemetry_log, drafts
):
    response = asyncio.run(wiki_refine.handler_get({"list_pending": True}))

    assert response["count"] == 2
    sample = _one_ok_sample(telemetry_log, "wiki_get_draft", response)
    assert sample["result_count"] == 2


def test_wiki_refine_draft_records_one_sample(telemetry_log, drafts):
    response = asyncio.run(wiki_refine.handler_refine({"draft_id": 7, "lead": "x"}))

    assert response["updated"] is True
    _one_ok_sample(telemetry_log, "wiki_refine_draft", response)


def test_a_raising_call_records_an_error_and_reraises(
    telemetry_log, drafts, monkeypatch
):
    def broken(*_a, **_k):
        raise RuntimeError("fixture: store broke")

    monkeypatch.setattr(wiki_refine, "get_draft", broken)
    with pytest.raises(RuntimeError, match="store broke"):
        asyncio.run(wiki_refine.handler_refine({"draft_id": 7, "lead": "x"}))

    [sample] = _samples(telemetry_log, "wiki_refine_draft")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, drafts):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await wiki_refine.handler_get({"list_pending": True})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "wiki_get_draft"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "wiki_get_draft") == []
