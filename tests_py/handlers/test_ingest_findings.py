"""Tests for ingest_findings.handler — orchestration over real fixture
artifacts on disk (tmp_path), fake store, and a fake PG connection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcp_server.handlers import ingest_findings


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_run(output_dir: Path, run_id: str, findings: dict[str, bool]) -> None:
    """findings: {finding_id: verified}."""
    _write_json(
        output_dir / "runs" / run_id / "index.json",
        {
            "run_id": run_id,
            "started_at": "2026-07-09T00:00:00Z",
            "last_updated_at": "2026-07-09T00:00:00Z",
            "findings": {
                fid: {
                    "artifact_path": f"findings/{fid}/stage-1.refined.json",
                    "extractor_version": "0.1.0",
                }
                for fid in findings
            },
        },
    )
    for fid, verified in findings.items():
        fdir = output_dir / "runs" / run_id / "findings" / fid
        _write_json(
            fdir / "stage-1.refined.json",
            {
                "extracted": {
                    "finding_id": fid,
                    "title": f"Title {fid}",
                    "description": f"Description {fid}",
                    "relevance_category": "bug",
                    "relevance_score": 0.5,
                    "extracted_at": "2026-07-09T00:00:00Z",
                    "extractor_version": "0.1.0",
                    "source_form": "inline",
                    "source_path": None,
                },
                "refined_prompt": {"text": "x", "role_hint": "engineer"},
                "refinement": {"added_context": [], "orchestrator_version": "0.1.0"},
            },
        )
        if verified is not None:
            _write_json(
                fdir / "stage-2.verified.json",
                {
                    "run_id": run_id,
                    "finding_id": fid,
                    "verified": verified,
                    "verified_kind": {
                        "schema_ok": True,
                        "completeness_ok": True,
                        "user_acknowledged": True,
                    },
                    "finalized_at": "2026-07-09T00:00:00Z",
                    "stage1_refined_path": f"findings/{fid}/stage-1.refined.json",
                    "session_path": f"findings/{fid}/stage-2.session.json",
                    "transcript_digest": "deadbeef",
                    "digest_algorithm": "sha256",
                    "transcript_bytes_at_finalize": 10,
                    "turn_count": 2,
                    "verifier_version": "0.1.0",
                    "completeness_checklist": {},
                },
            )


class _FakeStore:
    def __init__(self):
        self.memories: list[dict] = []
        self._next = 1000
        self._conn = MagicMock()
        cur = MagicMock()
        self._conn.cursor.return_value.__enter__.return_value = cur
        cur.fetchone.return_value = None  # no prior memo

    def insert_memory(self, data: dict) -> int:
        mid = self._next
        self._next += 1
        self.memories.append({**data, "id": mid})
        return mid

    def get_memories_by_tag(
        self, tag: str, limit: int = 20, heads_only: bool = True
    ) -> list[dict]:
        return [m for m in self.memories if tag in m.get("tags", [])]


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(ingest_findings, "_get_store", lambda: store)
    return store


@pytest.fixture
def no_wiki_page_write(monkeypatch):
    monkeypatch.setattr(
        "mcp_server.handlers.ingest_findings_writers.write_page",
        lambda *a, **k: None,
    )


@pytest.fixture
def no_upsert_page(monkeypatch):
    """upsert_page / upsert_page_sources / insert_memo are pure-SQL — stub
    them so this orchestration test doesn't need a live Postgres."""
    monkeypatch.setattr(
        "mcp_server.handlers.ingest_findings_writers.upsert_page",
        lambda conn, row: (777, True),
    )
    monkeypatch.setattr(
        "mcp_server.handlers.ingest_findings_writers.upsert_page_sources",
        lambda conn, page_id, sources, **kw: len(sources),
    )
    monkeypatch.setattr(
        "mcp_server.handlers.ingest_findings_writers.insert_memo",
        lambda conn, **kw: 1,
    )


class TestIngestFindingsHandler:
    @pytest.mark.asyncio
    async def test_missing_run_id_rejected(self, fake_store):
        result = await ingest_findings.handler({})
        assert result["ingested"] is False
        assert "run_id" in result["reason"]

    @pytest.mark.asyncio
    async def test_output_dir_not_resolved(self, fake_store, monkeypatch):
        monkeypatch.setattr(
            "mcp_server.handlers.ingest_findings.resolve_output_dir",
            lambda *a, **k: None,
        )
        result = await ingest_findings.handler({"run_id": "run1"})
        assert result["ingested"] is False
        assert result["reason"] == "output_dir_not_resolved"

    @pytest.mark.asyncio
    async def test_verified_and_hypothesis_findings_gradated(
        self, tmp_path, fake_store, no_wiki_page_write, no_upsert_page
    ):
        output_dir = tmp_path / "ap-output"
        _make_run(output_dir, "run1", {"f1": True, "f2": False})

        result = await ingest_findings.handler(
            {"run_id": "run1", "output_dir": str(output_dir)}
        )

        assert result["ingested"] is True
        assert result["findings_total"] == 2
        assert result["verified_count"] == 1
        assert result["hypothesis_count"] == 1
        by_id = {r["finding_id"]: r for r in result["results"]}
        assert by_id["f1"]["page_id"] == 777
        assert by_id["f1"]["memos_written"] == 1
        assert by_id["f2"]["page_id"] is None
        assert by_id["f2"]["memos_written"] == 0
        # Gradation reflected in memory tags.
        f1_tags = [
            m["tags"] for m in fake_store.memories if "ap-finding:run1:f1" in m["tags"]
        ][0]
        f2_tags = [
            m["tags"] for m in fake_store.memories if "ap-finding:run1:f2" in m["tags"]
        ][0]
        assert "verified" in f1_tags
        assert "hypothesis" in f2_tags

    @pytest.mark.asyncio
    async def test_malformed_artifact_reported_not_raised(
        self, tmp_path, fake_store, no_wiki_page_write, no_upsert_page
    ):
        output_dir = tmp_path / "ap-output"
        _make_run(output_dir, "run1", {"f1": True})
        # Corrupt f1's refined artifact after index.json was written.
        refined_path = (
            output_dir / "runs" / "run1" / "findings" / "f1" / "stage-1.refined.json"
        )
        refined_path.write_text("not json", encoding="utf-8")

        result = await ingest_findings.handler(
            {"run_id": "run1", "output_dir": str(output_dir)}
        )

        assert result["ingested"] is True
        assert result["findings_total"] == 0
        assert len(result["errors"]) == 1
        assert "f1" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_reingestion_is_idempotent(
        self, tmp_path, fake_store, no_wiki_page_write, no_upsert_page
    ):
        output_dir = tmp_path / "ap-output"
        _make_run(output_dir, "run1", {"f1": True})

        first = await ingest_findings.handler(
            {"run_id": "run1", "output_dir": str(output_dir)}
        )
        second = await ingest_findings.handler(
            {"run_id": "run1", "output_dir": str(output_dir)}
        )

        assert first["verified_count"] == second["verified_count"] == 1
        # Exactly one memory row exists after both runs (dedup via tag lookup).
        assert len(fake_store.memories) == 1
        assert second["results"][0]["memory_created"] is False
