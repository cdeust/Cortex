"""BLE001 sweep (issue #197, second family): handler-layer sites that
gained a ``silent_failure`` signal.

Each test forces the guarded operation to fail and asserts the
now-visible ``silent_failure`` signal AND that the pre-existing fallback
behaviour is unchanged (same contract as test_s110_sweep_handlers.py).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from mcp_server.observability import silent_failure

WARN_LOGGER = "mcp_server.observability.silent_failure"


@pytest.fixture(autouse=True)
def _reset():
    silent_failure.reset()
    yield
    silent_failure.reset()


def _assert_noted(component: str, error_text: str) -> None:
    """Exact-component check via silent_failure.status()."""
    status = silent_failure.status()
    assert component in status
    assert error_text in str(status[component]["last_error"])


class TestIngestTagLookupSites:
    """Tag-query failures remain observable; document recovery fails closed."""

    def test_docs_content_find_existing_failure_is_logged(self):
        from mcp_server.handlers.ingest_docs_content_writers import (
            find_existing_doc_memory,
        )

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        assert find_existing_doc_memory(store, "dom", "a/b.md") is None
        _assert_noted("ingest_docs_content.find_existing_doc", "tag query broke")

    def test_document_lookup_failure_is_reported_and_logged(self):
        from mcp_server.core.document_model import DocumentProvenance
        from mcp_server.core.document_normalizer import NormalizedDocument
        from mcp_server.handlers.ingest_document_writers import (
            DocumentMemoryContext,
            write_document_memories,
        )

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        prov = DocumentProvenance("/d.docx", "v1", "docx")
        normalized = NormalizedDocument("documents/d.md", "# D", "summary")
        result = write_document_memories(
            DocumentMemoryContext(store, prov, "dom", "/"), normalized
        )
        assert result["failures"] == {"memory_lookup": "tag query broke"}
        store.insert_memory.assert_not_called()
        _assert_noted("ingest_document.memory_lookup", "tag query broke")

    def test_findings_graph_key_lookup_failure_is_logged(self):
        from mcp_server.handlers.ingest_findings_resolve import _from_graph_key

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        assert _from_graph_key(store, "k1") is None
        _assert_noted("ingest_findings.graph_key_lookup", "tag query broke")

    def test_findings_find_existing_failure_is_logged(self):
        from mcp_server.handlers.ingest_findings_writers import find_existing_memory

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        assert find_existing_memory(store, "r1", "f1") is None
        _assert_noted("ingest_findings.find_existing", "tag query broke")


class TestIngestHelpersSites:
    def test_cached_graph_lookup_failure_degrades_to_none_and_is_logged(self):
        from mcp_server.handlers.ingest_helpers import find_cached_graph

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        assert find_cached_graph(store, "/proj") is None
        _assert_noted("ingest_helpers.cached_graph_lookup", "tag query broke")

    def test_graph_memo_insert_failure_degrades_to_none_and_is_logged(self):
        from mcp_server.handlers.ingest_helpers import memoise_graph_path

        store = MagicMock()
        store.insert_memory.side_effect = RuntimeError("insert broke")
        assert memoise_graph_path(store, "/proj", "/g.json") is None
        _assert_noted("ingest_helpers.graph_memo_insert", "insert broke")


class TestLessonPromotionCandidates:
    def test_store_failure_degrades_to_no_jobs_and_is_logged(self, monkeypatch):
        from mcp_server.handlers import lesson_promotion

        def broken():
            raise RuntimeError("store down")

        monkeypatch.setattr(lesson_promotion, "get_shared_store", broken)
        out = asyncio.run(lesson_promotion.handler({"limit": 3}))
        assert out["jobs"] == []
        _assert_noted("lesson_promotion.candidates", "store down")


class TestRateMemoryValueUpdate:
    def test_value_update_failure_keeps_rating_and_is_logged(self, monkeypatch):
        from mcp_server.handlers import rate_memory

        store = MagicMock()
        store.get_memory.return_value = {
            "access_count": 1,
            "useful_count": 1,
            "importance": 0.5,
            "content": "c",
            "value": 0.4,
        }
        store.update_memory_value.side_effect = RuntimeError("value column missing")
        monkeypatch.setattr(rate_memory, "_get_store", lambda: store)
        monkeypatch.setattr(rate_memory, "_record_platt_sample", lambda q, c, u: False)
        out = asyncio.run(rate_memory._handler_impl({"memory_id": 1, "useful": True}))
        assert out.get("rated") is True
        store.update_memory_metamemory.assert_called_once()
        _assert_noted("rate_memory.value_update", "value column missing")


class TestRecallHelpersProspectiveTriggers:
    def test_trigger_fetch_failure_keeps_results_and_is_logged(self):
        from mcp_server.handlers.recall_helpers import inject_triggered_memories

        store = MagicMock()
        store.get_active_prospective_memories.side_effect = RuntimeError("pg down")
        results = [{"memory_id": 7}]
        assert inject_triggered_memories(results, "q", store) is results
        _assert_noted("recall_helpers.prospective_triggers", "pg down")


class TestRememberHelpersBuildRecord:
    MOD = {
        "heat": 0.5,
        "importance": 0.5,
        "valence": 0.0,
        "theta": 0.0,
        "enc_mod": 1.0,
        "schema_match": 0.0,
        "schema_id": None,
        "emotional_tag": None,
    }

    def _build(self):
        from mcp_server.handlers.remember_helpers import _build_insert_record

        return _build_insert_record(
            "content",
            None,
            [],
            "test",
            "dom",
            "",
            dict(self.MOD),
            0.5,
            False,
            "episodic",
            0.0,
            0.0,
        )

    def test_source_attribution_failure_degrades_to_unknown_and_is_logged(
        self, monkeypatch
    ):
        from mcp_server.core import source_monitoring

        def broken(content, source_field):
            raise RuntimeError("classifier broke")

        monkeypatch.setattr(source_monitoring, "classify_source", broken)
        record = self._build()
        assert record["source_attribution"] == "unknown"
        _assert_noted("remember_helpers.source_attribution", "classifier broke")

    def test_stimulus_signature_failure_degrades_to_empty_and_is_logged(
        self, monkeypatch
    ):
        from mcp_server.core import habituation

        def broken(content):
            raise RuntimeError("signature broke")

        monkeypatch.setattr(habituation, "stimulus_signature", broken)
        record = self._build()
        assert record["stimulus_signature"] == ""
        _assert_noted("remember_helpers.stimulus_signature", "signature broke")


class TestWikiPointerMemories:
    def test_wiki_adr_pointer_failure_is_swallowed_and_logged(self, monkeypatch):
        from mcp_server.handlers import remember, wiki_adr

        async def broken(args):
            raise RuntimeError("remember broke")

        monkeypatch.setattr(remember, "handler", broken)
        asyncio.run(wiki_adr._store_pointer_memory("adr/x.md", "content", ["t"]))
        _assert_noted("wiki_adr.pointer_memory", "remember broke")

    def test_wiki_write_pointer_failure_is_swallowed_and_logged(self, monkeypatch):
        from mcp_server.handlers import remember, wiki_write

        async def broken(args):
            raise RuntimeError("remember broke")

        monkeypatch.setattr(remember, "handler", broken)
        asyncio.run(wiki_write._store_pointer_memory("notes/x.md", "content", ["t"]))
        _assert_noted("wiki_write.pointer_memory", "remember broke")


class TestWikiWriteSessionLookup:
    def test_session_lookup_failure_degrades_to_empty_and_is_logged(self, monkeypatch):
        from mcp_server.handlers import wiki_write

        store = MagicMock()
        monkeypatch.setattr(wiki_write, "get_memory_settings", MagicMock())
        monkeypatch.setattr(wiki_write, "get_shared_store", lambda *a, **k: store)
        monkeypatch.setattr(
            wiki_write, "page_row_from_md", lambda rel, content: {"slug": rel}
        )
        monkeypatch.setattr(wiki_write, "upsert_page", lambda conn, row: (1, False))

        def broken():
            raise RuntimeError("registry broke")

        monkeypatch.setattr(wiki_write, "current_window_session", broken)
        inserted = []

        def fake_citation(conn, **kwargs):
            inserted.append(kwargs)
            return 1

        monkeypatch.setattr(wiki_write, "insert_citation", fake_citation)
        written = wiki_write._sync_page_and_cite("notes/x.md", "content", [42])
        assert written == 1
        assert inserted[0]["session_id"] == ""
        _assert_noted("wiki_write.session_lookup", "registry broke")
