"""Unit tests for ingest_docs_content.run_docs_pass (INC5.3/D6) —
cypher + writers monkeypatched, no live Postgres or upstream MCP
required."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.handlers import ingest_docs_content as docs_content
from mcp_server.handlers import ingest_docs_content_cypher as cypher
from mcp_server.handlers import ingest_docs_content_writers as writers


class _FakeStore:
    """Only used as an opaque token passed through to the writers — the
    writers themselves are monkeypatched in these orchestrator tests."""


@pytest.mark.asyncio
class TestRunDocsPass:
    async def test_writes_one_memory_per_readable_doc_and_skips_oversized(
        self, tmp_path: Path, monkeypatch
    ):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "a.md").write_text("content A", encoding="utf-8")
        (tmp_path / "docs" / "b.md").write_text("content B", encoding="utf-8")

        async def _fetch_doc_files(graph_path):
            assert graph_path == "/g"
            return (
                [
                    {"path": "docs/a.md"},
                    {"path": "docs/b.md"},
                    {"path": "docs/missing.md"},  # not on disk -> skipped
                ],
                [],
            )

        async def _fetch_doc_references(graph_path, known_doc_paths):
            assert known_doc_paths == {"docs/a.md", "docs/b.md", "docs/missing.md"}
            return [("docs/a.md", "docs/b.md")], []

        written_memories: list[tuple[str, str]] = []
        written_edges: list[tuple[str, str]] = []

        def _write_doc_memory(store, domain, directory_context, rel_path, content):
            written_memories.append((rel_path, content))
            return (1, True, False)

        def _write_doc_reference_edge(store, src, dst):
            written_edges.append((src, dst))
            return True

        monkeypatch.setattr(cypher, "fetch_doc_files", _fetch_doc_files)
        monkeypatch.setattr(cypher, "fetch_doc_references", _fetch_doc_references)
        monkeypatch.setattr(writers, "write_doc_memory", _write_doc_memory)
        monkeypatch.setattr(
            writers, "write_doc_reference_edge", _write_doc_reference_edge
        )

        result = await docs_content.run_docs_pass(
            _FakeStore(), "/g", str(tmp_path), "code:proj"
        )

        assert result["docs_seen"] == 3
        assert result["docs_written"] == 2
        assert result["docs_superseded"] == 0
        assert result["docs_skipped"] == 1
        assert result["references_written"] == 1
        assert ("docs/a.md", "content A") in written_memories
        assert ("docs/b.md", "content B") in written_memories
        assert written_edges == [("docs/a.md", "docs/b.md")]

    async def test_no_docs_found_is_a_clean_zero_result(self, tmp_path, monkeypatch):
        async def _empty(*args, **kwargs):
            return [], []

        monkeypatch.setattr(cypher, "fetch_doc_files", _empty)
        monkeypatch.setattr(cypher, "fetch_doc_references", _empty)

        result = await docs_content.run_docs_pass(
            _FakeStore(), "/g", str(tmp_path), "code:proj"
        )
        assert result == {
            "docs_seen": 0,
            "docs_written": 0,
            "docs_superseded": 0,
            "docs_skipped": 0,
            "references_written": 0,
        }

    async def test_reingesting_unchanged_docs_writes_nothing_new(
        self, tmp_path: Path, monkeypatch
    ):
        """Idempotence at the orchestrator level: write_doc_memory reporting
        created=False (as it does on re-ingestion, per its own unit tests)
        must not be counted as a fresh write."""
        (tmp_path / "a.md").write_text("content", encoding="utf-8")

        async def _fetch_doc_files(graph_path):
            return [{"path": "a.md"}], []

        async def _fetch_doc_references(graph_path, known_doc_paths):
            return [], []

        def _write_doc_memory_existing(
            store, domain, directory_context, rel_path, content
        ):
            return (555, False, False)  # already ingested, unchanged

        monkeypatch.setattr(cypher, "fetch_doc_files", _fetch_doc_files)
        monkeypatch.setattr(cypher, "fetch_doc_references", _fetch_doc_references)
        monkeypatch.setattr(writers, "write_doc_memory", _write_doc_memory_existing)

        result = await docs_content.run_docs_pass(
            _FakeStore(), "/g", str(tmp_path), "code:proj"
        )
        assert result["docs_seen"] == 1
        assert result["docs_written"] == 0  # written=False -> not counted
        assert result["docs_superseded"] == 0

    async def test_reingesting_changed_doc_counts_as_superseded(
        self, tmp_path: Path, monkeypatch
    ):
        """Orchestrator-level regression for issue #381: a doc whose source
        changed since capture must surface as both a write AND a
        supersession, not merely a write (which would be indistinguishable
        from a first-time capture in the response counts)."""
        (tmp_path / "a.md").write_text("new content", encoding="utf-8")

        async def _fetch_doc_files(graph_path):
            return [{"path": "a.md"}], []

        async def _fetch_doc_references(graph_path, known_doc_paths):
            return [], []

        def _write_doc_memory_changed(
            store, domain, directory_context, rel_path, content
        ):
            return (556, True, True)  # stale snapshot superseded

        monkeypatch.setattr(cypher, "fetch_doc_files", _fetch_doc_files)
        monkeypatch.setattr(cypher, "fetch_doc_references", _fetch_doc_references)
        monkeypatch.setattr(writers, "write_doc_memory", _write_doc_memory_changed)

        result = await docs_content.run_docs_pass(
            _FakeStore(), "/g", str(tmp_path), "code:proj"
        )
        assert result["docs_seen"] == 1
        assert result["docs_written"] == 1
        assert result["docs_superseded"] == 1

    async def test_diagnostics_from_both_fetchers_are_merged(
        self, tmp_path: Path, monkeypatch
    ):
        async def _fetch_doc_files(graph_path):
            return [], ["files-error"]

        async def _fetch_doc_references(graph_path, known_doc_paths):
            return [], ["refs-error"]

        monkeypatch.setattr(cypher, "fetch_doc_files", _fetch_doc_files)
        monkeypatch.setattr(cypher, "fetch_doc_references", _fetch_doc_references)

        result = await docs_content.run_docs_pass(
            _FakeStore(), "/g", str(tmp_path), "code:proj"
        )
        assert result["diagnostics"] == ["files-error", "refs-error"]
