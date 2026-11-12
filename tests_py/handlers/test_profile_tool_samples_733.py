"""Three profile tools record one telemetry sample per call (#733).

Before, ``detect_domain``, ``list_domains`` and ``rebuild_profiles`` were
registered without ``instrument``: their wall time, bytes and outcome were
absent from ``get_telemetry`` and the JSONL
(docs/audits/operation-consumption-inventory-2026-11-05.md). These tests drive
each registered ``handler`` and read the JSONL sink. The profile store and the
transcript scan are replaced by doubles: the tests are about the sample, not
the profiles, which ``test_list_domains.py`` and ``test_rebuild_profiles.py``
cover.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_core import to_json

from mcp_server.core import telemetry
from mcp_server.handlers import detect_domain, list_domains, rebuild_profiles

_PROFILES = {
    "domains": {
        "a": {"id": "a", "label": "A", "sessionCount": 2},
        "b": {"id": "b", "label": "B", "sessionCount": 1},
    }
}


@pytest.fixture
def telemetry_log(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.jsonl"
    monkeypatch.setattr(telemetry, "_LOG_PATH", path)
    monkeypatch.delenv("CORTEX_TELEMETRY_DISABLED", raising=False)
    telemetry.reset()
    yield path
    telemetry.reset()


@pytest.fixture
def profiles(monkeypatch):
    for module in (detect_domain, list_domains):
        monkeypatch.setattr(module, "load_profiles", lambda: _PROFILES)


@pytest.fixture
def rescan(monkeypatch):
    build = SimpleNamespace(profiles=_PROFILES, outcomes=[])
    monkeypatch.setattr(rebuild_profiles, "load_profiles", lambda: {})
    monkeypatch.setattr(rebuild_profiles, "discover_all_memories", lambda: [])
    monkeypatch.setattr(rebuild_profiles, "discover_conversations", lambda: [])
    monkeypatch.setattr(rebuild_profiles, "discover_codex_conversations", lambda: [])
    monkeypatch.setattr(rebuild_profiles, "group_by_project", lambda _c: {})
    monkeypatch.setattr(rebuild_profiles, "load_brain_index", lambda: {})
    monkeypatch.setattr(rebuild_profiles, "build_domain_profiles", lambda **_k: build)
    monkeypatch.setattr(rebuild_profiles, "save_profiles", lambda _p: None)


def _samples(path, op: str) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [s for s in map(json.loads, lines) if s["op"] == op]


def _one_ok_sample(path, op: str, response: dict) -> dict:
    [sample] = _samples(path, op)
    assert (sample["ok"], sample["skipped"]) == (True, False)
    assert sample["bytes_out"] == len(to_json(response, fallback=str, indent=2))
    assert telemetry.snapshot()[op]["count"] == 1
    return sample


def test_detect_domain_records_one_sample(telemetry_log, profiles):
    response = asyncio.run(detect_domain.handler({"cwd": "/code/a"}))

    assert "domain" in response
    _one_ok_sample(telemetry_log, "detect_domain", response)


def test_list_domains_records_one_sample_counting_domains(telemetry_log, profiles):
    response = asyncio.run(list_domains.handler({}))

    assert response["totalDomains"] == 2
    sample = _one_ok_sample(telemetry_log, "list_domains", response)
    assert sample["result_count"] == 2


def test_rebuild_profiles_records_one_sample(telemetry_log, rescan):
    response = asyncio.run(rebuild_profiles.handler({"force": True}))

    assert response["domains"] == ["a", "b"]
    _one_ok_sample(telemetry_log, "rebuild_profiles", response)


def test_a_raising_call_records_an_error_and_reraises(telemetry_log, monkeypatch):
    def broken():
        raise RuntimeError("fixture: profiles unreadable")

    monkeypatch.setattr(list_domains, "load_profiles", broken)
    with pytest.raises(RuntimeError, match="profiles unreadable"):
        asyncio.run(list_domains.handler({}))

    [sample] = _samples(telemetry_log, "list_domains")
    assert (sample["ok"], sample["skipped"], sample["bytes_out"]) == (False, False, 0)


def test_a_call_inside_an_mcp_request_carries_its_operation_id(telemetry_log, profiles):
    async def call() -> list[telemetry.TelemetrySample]:
        with telemetry.capture_records() as samples:
            await detect_domain.handler({})
        return samples

    captured = asyncio.run(call())
    [sample] = [s for s in captured if s["op"] == "detect_domain"]
    assert sample["operation_id"]
    assert _samples(telemetry_log, "detect_domain") == []
