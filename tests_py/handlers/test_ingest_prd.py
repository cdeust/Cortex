"""Tests for ingest_prd — fake upstream + store + wiki."""

from __future__ import annotations

import pytest

from mcp_server.handlers import ingest_prd


class _FakeStore:
    def __init__(self):
        self.memories: list[dict] = []
        self._next = 5000

    def insert_memory(self, data: dict) -> int:
        mid = self._next
        self._next += 1
        data["id"] = mid
        self.memories.append(data)
        return mid


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(ingest_prd, "_get_store", lambda: store)
    return store


@pytest.fixture
def no_wiki(monkeypatch):
    written: list[tuple[str, str]] = []

    def _write(_root, rel, content, mode="replace"):
        written.append((rel, content))

    monkeypatch.setattr(ingest_prd, "write_page", _write)
    return written


_SAMPLE_PRD = """# Auth v2 redesign

## Context
We need to rotate secrets monthly.

## Decisions

- Adopt HKDF-SHA256 for key derivation
- Store rotating keys in AWS KMS
- Reject plaintext secrets in Git

## Requirements
- All new services MUST encrypt at rest with AES-256
- Audit log MUST capture every rotation event
- Incident response SHOULD notify on-call within 5 minutes
"""


class TestIngestPrdSources:
    @pytest.mark.asyncio
    async def test_content_source_extracts_decisions_and_requirements(
        self, fake_store, no_wiki
    ):
        result = await ingest_prd.handler({"content": _SAMPLE_PRD})

        assert result["ingested"] is True
        assert result["title"] == "Auth v2 redesign"
        assert result["source"] == "content"
        assert result["decision_count"] == 3
        assert result["requirement_count"] == 3
        # Spec page written under specs/<slug>.md
        assert result["wiki_path"].startswith("specs/")
        assert no_wiki and "Auth v2 redesign" in no_wiki[0][1]

    @pytest.mark.asyncio
    async def test_title_override(self, fake_store, no_wiki):
        result = await ingest_prd.handler(
            {"content": _SAMPLE_PRD, "title": "Custom Title"}
        )
        assert result["title"] == "Custom Title"

    @pytest.mark.asyncio
    async def test_pipeline_id_source_calls_upstream(
        self, fake_store, no_wiki, monkeypatch
    ):
        calls = []

        async def _call(server, tool, args):
            calls.append((server, tool, args))
            return {"rendered_prd": _SAMPLE_PRD}

        monkeypatch.setattr(ingest_prd, "call_upstream", _call)

        result = await ingest_prd.handler({"pipeline_id": "pipe-123"})

        assert result["ingested"] is True
        assert result["source"] == "pipeline_id"
        assert calls[0][1] == "get_pipeline_state"
        assert calls[0][2]["pipeline_id"] == "pipe-123"

    @pytest.mark.asyncio
    async def test_zero_sources_rejected(self, fake_store):
        result = await ingest_prd.handler({})
        assert result["ingested"] is False
        assert "exactly one" in result["reason"]

    @pytest.mark.asyncio
    async def test_two_sources_rejected(self, fake_store):
        result = await ingest_prd.handler({"content": _SAMPLE_PRD, "path": "/tmp/x.md"})
        assert result["ingested"] is False
        assert "exactly one" in result["reason"]


class TestIngestPrdValidation:
    @pytest.mark.asyncio
    async def test_validate_true_calls_prd_gen(self, fake_store, no_wiki, monkeypatch):
        calls = []

        async def _call(server, tool, args):
            calls.append((server, tool, args))
            return {"quality_score": 0.87, "issues": []}

        monkeypatch.setattr(ingest_prd, "call_upstream", _call)

        result = await ingest_prd.handler({"content": _SAMPLE_PRD, "validate": True})

        assert result["ingested"] is True
        assert result["validation"]["quality_score"] == 0.87
        assert calls[0][1] == "validate_prd_document"

    @pytest.mark.asyncio
    async def test_validate_false_skips_upstream(
        self, fake_store, no_wiki, monkeypatch
    ):
        async def _call(server, tool, args):
            raise AssertionError("should not call upstream when validate=False")

        monkeypatch.setattr(ingest_prd, "call_upstream", _call)

        result = await ingest_prd.handler({"content": _SAMPLE_PRD})
        assert result["validation"] is None
