"""Five wiki tools record one telemetry sample per call (#733).

Before, ``wiki_read``, ``wiki_list``, ``wiki_link``, ``wiki_verify`` and
``wiki_rename`` were registered without ``instrument``: their wall time, bytes
and outcome were absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` against a temporary wiki root and read the JSONL
sink.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.core.wiki_identity import generate_page_id
from mcp_server.handlers import (
    wiki_link,
    wiki_list,
    wiki_read,
    wiki_rename,
    wiki_verify,
)


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


@pytest.fixture
def wiki(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "wiki"
    for mod in (wiki_read, wiki_list, wiki_link, wiki_rename, wiki_verify):
        monkeypatch.setattr(mod, "WIKI_ROOT", str(root))
    for name in ("one", "two"):
        page = root / "explanation" / f"{name}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(
            f"---\nid: {generate_page_id()}\ntitle: {name}\nkind: explanation\n"
            f"provenance: human\n---\n\n# {name}\n\nBody.\n",
            encoding="utf-8",
        )
    return root


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


def _one_ok_sample(path, op: str, response: dict) -> dict:
    [sample] = _samples(path, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1
    return sample


def test_wiki_list_records_one_sample_counting_its_pages(telemetry_log, wiki):
    response = asyncio.run(wiki_list.handler({}))

    sample = _one_ok_sample(telemetry_log, "wiki_list", response)
    assert response["count"] == 2
    assert sample["result_count"] == 2


def test_wiki_read_records_one_sample(telemetry_log, wiki):
    response = asyncio.run(wiki_read.handler({"path": "explanation/one.md"}))

    assert "content" in response
    _one_ok_sample(telemetry_log, "wiki_read", response)


def test_wiki_link_records_one_sample(telemetry_log, wiki):
    args = {
        "from_path": "explanation/one.md",
        "to_path": "explanation/two.md",
        "relation": "see_also",
    }
    response = asyncio.run(wiki_link.handler(args))

    assert "error" not in response
    _one_ok_sample(telemetry_log, "wiki_link", response)


def test_wiki_rename_records_one_sample(telemetry_log, wiki):
    args = {"from_path": "explanation/one.md", "to_path": "explanation/three.md"}
    response = asyncio.run(wiki_rename.handler(args))

    assert response["stub_created"] is True
    _one_ok_sample(telemetry_log, "wiki_rename", response)


def test_wiki_verify_records_one_sample_counting_its_results(
    telemetry_log, wiki, monkeypatch
):
    monkeypatch.setattr(wiki_verify, "is_enabled", lambda: True)
    monkeypatch.setattr(wiki_verify, "WorkflowGraphASTSource", lambda: None)
    monkeypatch.setattr(wiki_verify, "_verify_one", lambda p, _s: {"path": p})

    response = asyncio.run(wiki_verify.handler({}))

    sample = _one_ok_sample(telemetry_log, "wiki_verify", response)
    assert sample["result_count"] == len(response["results"]) == 2


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, wiki, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("fixture: listing broke")

    monkeypatch.setattr(wiki_list, "list_pages", broken)
    with pytest.raises(RuntimeError, match="listing broke"):
        asyncio.run(wiki_list.handler({}))

    [sample] = _samples(telemetry_log, "wiki_list")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, wiki):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await wiki_list.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "wiki_list"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "wiki_list") == []
