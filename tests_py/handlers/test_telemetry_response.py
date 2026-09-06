"""W0-1: response bytes and request-scoped retrieval work are observable."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.handlers import recall, remember
from mcp_server.shared.telemetry_context import count_reranked, set_retrieval_tier


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


def test_public_recall_remember_record_response_bytes(telemetry_log):
    """Even empty-query / rejected-write responses carry serialized output."""
    responses = [asyncio.run(recall.handler({})), asyncio.run(remember.handler({}))]
    samples = [json.loads(line) for line in telemetry_log.read_text().splitlines()]
    assert [sample["op"] for sample in samples] == ["recall", "remember"]
    for sample, response in zip(samples, responses, strict=True):
        assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
        assert sample["bytes_out"] > 0
        assert sample["tier"] is None
        assert sample["reranked_count"] == 0


def test_wrapper_preserves_result_and_records_failure(telemetry_log):
    async def fail(args):
        raise ValueError("fixture failure")

    with pytest.raises(ValueError, match="fixture failure"):
        asyncio.run(instrument("fixture", fail)({"query": "café"}))
    sample = json.loads(telemetry_log.read_text())
    assert sample["ok"] is False
    assert sample["bytes_out"] == 0
    assert sample["bytes_in"] == len(json.dumps({"query": "café"}).encode("utf-8"))


def test_unicode_response_matches_sdk_and_records_retrieval_work(telemetry_log):
    response = {"memories": [{"id": 1, "content": "café 🧠"}]}

    async def retrieve(args):
        set_retrieval_tier("pg")
        count_reranked(2)
        return response

    assert asyncio.run(instrument("recall", retrieve)({})) is response
    sample = json.loads(telemetry_log.read_text())
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert sample["bytes_out"] > len(to_json(response, indent=2).decode("utf-8"))
    assert sample["tier"] == "pg"
    assert sample["reranked_count"] == 2


def test_cancelled_handler_records_failure_and_restores_metrics(telemetry_log):
    async def cancel(args):
        set_retrieval_tier("deep")
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(instrument("recall", cancel)({}))
    asyncio.run(recall.handler({}))
    samples = [json.loads(line) for line in telemetry_log.read_text().splitlines()]
    assert samples[0]["ok"] is False
    assert samples[0]["tier"] == "deep"
    assert samples[1]["tier"] is None


def test_real_store_round_trip_records_nonempty_response_sizes(telemetry_log):
    content = "We decided to verify UTF-8 telemetry with an isolated SQLite store."
    stored = asyncio.run(remember.handler({"content": content, "force": True}))
    assert stored["stored"] is True
    telemetry_log.write_text("")
    recalled = asyncio.run(recall.handler({"query": "UTF-8 telemetry"}))
    written = asyncio.run(
        remember.handler({"content": "Follow-up decision", "force": True})
    )
    assert recalled["count"] > 0
    assert written["stored"] is True
    samples = [json.loads(line) for line in telemetry_log.read_text().splitlines()]
    assert [sample["op"] for sample in samples] == ["recall", "remember"]
    for sample, response in zip(samples, [recalled, written], strict=True):
        assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
        assert sample["bytes_out"] > 0
        assert "tier" in sample and "reranked_count" in sample
    assert samples[0]["tier"] == "pg"
