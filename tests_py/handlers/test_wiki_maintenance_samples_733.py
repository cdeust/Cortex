"""Three wiki maintenance tools record one telemetry sample per call (#733).

Before, ``wiki_reindex``, ``wiki_purge`` and ``wiki_migrate`` were registered
without ``instrument``: their wall time, bytes and outcome were absent from
``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` against a temporary wiki root and read the JSONL
sink. ``wiki_migrate`` needs a PostgreSQL store, so its store and migration are
replaced by doubles: the test is about the sample, not the migration.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.core.wiki_identity import generate_page_id
from mcp_server.handlers import wiki_migrate, wiki_purge, wiki_reindex


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
    for mod in (wiki_reindex, wiki_purge):
        monkeypatch.setattr(mod, "WIKI_ROOT", str(root))
    page = root / "explanation" / "one.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        f"---\nid: {generate_page_id()}\ntitle: one\nkind: explanation\n"
        "provenance: human\n---\n\n# one\n\nA body long enough to be kept.\n",
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


def test_wiki_reindex_records_one_sample(telemetry_log, wiki):
    response = asyncio.run(wiki_reindex.handler({}))

    assert "error" not in response
    _one_ok_sample(telemetry_log, "wiki_reindex", response)


def test_wiki_purge_records_one_sample(telemetry_log, wiki):
    response = asyncio.run(wiki_purge.handler({}))

    assert response["applied"] is False
    _one_ok_sample(telemetry_log, "wiki_purge", response)


def test_wiki_migrate_records_one_sample(telemetry_log, monkeypatch):
    store = SimpleNamespace(_conn=object())
    monkeypatch.setattr(wiki_migrate, "get_shared_store", lambda *_a: store)

    def migrate(_root, conn, *, dry_run):
        return {"dry_run": dry_run, "same": conn is store._conn}

    monkeypatch.setattr(wiki_migrate, "migrate_wiki", migrate)

    response = asyncio.run(wiki_migrate.handler({}))

    assert response == {"dry_run": True, "same": True}
    _one_ok_sample(telemetry_log, "wiki_migrate", response)


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, wiki, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("fixture: scan broke")

    monkeypatch.setattr(wiki_purge, "candidate_pages", broken)
    with pytest.raises(RuntimeError, match="scan broke"):
        asyncio.run(wiki_purge.handler({}))

    [sample] = _samples(telemetry_log, "wiki_purge")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, wiki):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await wiki_reindex.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "wiki_reindex"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "wiki_reindex") == []
