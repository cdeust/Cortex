"""Five memory tools record one telemetry sample per call (issue #733).

Before, ``unified_search``, ``memory_stats``, ``checkpoint``, ``narrative`` and
``import_sessions`` were registered without ``instrument``: their wall time,
bytes and outcome were absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import (
    checkpoint,
    import_sessions,
    memory_stats,
    narrative,
    unified_search,
)


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


# Calls that return without touching the store or the network: an argument the
# handler refuses, or a query that matches nothing.
_CALLS = [
    ("checkpoint", checkpoint, {}),
    ("checkpoint", checkpoint, {"action": "neither"}),
    ("narrative", narrative, {"brief": True}),
    ("memory_stats", memory_stats, {}),
]


@pytest.mark.parametrize(("op", "module", "args"), _CALLS)
def test_a_call_records_one_sample_with_its_bytes(telemetry_log, op, module, args):
    response = asyncio.run(module.handler(args))

    [sample] = _samples(telemetry_log, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_in"] == (len(json.dumps(args).encode("utf-8")) if args else 0)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1


def test_import_sessions_counts_the_imported_items(telemetry_log, monkeypatch):
    monkeypatch.setattr(import_sessions, "_discover_jsonl_files", lambda _p: [])

    response = asyncio.run(import_sessions.handler({"dry_run": True}))

    [sample] = _samples(telemetry_log, "import_sessions")
    assert response["imported"] == 0
    assert (sample["ok"], sample["result_count"]) == (True, 0)


def test_unified_search_counts_its_results(telemetry_log, monkeypatch):
    hits = [{"id": "wiki:a.md", "content": "a"}, {"id": "wiki:b.md", "content": "b"}]
    exact = {"status": "ok", "memories": hits}
    monkeypatch.setattr(unified_search, "exact_lookup", lambda _args: exact)

    response = asyncio.run(unified_search.handler({"query": "a"}))

    [sample] = _samples(telemetry_log, "unified_search")
    assert len(response["results"]) == 2
    assert (sample["ok"], sample["result_count"]) == (True, 2)


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("fixture: store unreachable")

    monkeypatch.setattr(memory_stats, "_get_store", broken)
    with pytest.raises(RuntimeError, match="store unreachable"):
        asyncio.run(memory_stats.handler({}))

    [sample] = _samples(telemetry_log, "memory_stats")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await checkpoint.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "checkpoint"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "checkpoint") == []
