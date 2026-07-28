"""BLE001 sweep (issue #197, second family): infrastructure-layer sites
that gained a signal (``silent_failure`` or a logger emission).

Each test forces the guarded operation to fail and asserts the
now-visible signal AND that the pre-existing fallback behaviour is
unchanged (same contract as test_s110_sweep_handlers.py).
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


class TestApBridgeSettingsRead:
    def test_settings_failure_keeps_on_by_default_and_is_logged(self, monkeypatch):
        from mcp_server.infrastructure import ap_bridge, memory_config

        def broken():
            raise RuntimeError("pydantic broke")

        monkeypatch.setattr(memory_config, "get_memory_settings", broken)
        assert ap_bridge.is_enabled() is True
        _assert_noted("ap_bridge.settings_read", "pydantic broke")


class TestGroomerCoordinatorStoreIdentity:
    def test_settings_failure_degrades_to_default_key_and_is_logged(self, monkeypatch):
        from mcp_server.infrastructure import groomer_coordinator, memory_config

        def broken():
            raise RuntimeError("pydantic broke")

        monkeypatch.setattr(memory_config, "get_memory_settings", broken)
        assert groomer_coordinator.resolve_store_key({}) == "default"
        _assert_noted("groomer_coordinator.store_identity", "pydantic broke")


class TestWikiSchemaReaderParsing:
    def test_page_parse_failure_skips_file_and_is_logged(self, tmp_path):
        from mcp_server.infrastructure.wiki_schema_reader import _load_folder_direct

        folder = tmp_path / "_kinds"
        folder.mkdir()
        (folder / "adr.md").write_text("---\nname: adr\n---\nbody", encoding="utf-8")

        def broken_parser(rel, content):
            raise RuntimeError("kind schema broke")

        assert _load_folder_direct(tmp_path, "_kinds", broken_parser) == {}
        _assert_noted("wiki_schema_reader.page_parse", "kind schema broke")

    def test_rules_parse_failure_skips_file_and_is_logged(self, tmp_path, monkeypatch):
        from mcp_server.infrastructure import wiki_schema_reader

        rules_dir = tmp_path / "_rules"
        rules_dir.mkdir()
        (rules_dir / "r.md").write_text("| a | b |\n", encoding="utf-8")

        def broken(body):
            raise RuntimeError("rules table broke")

        monkeypatch.setattr(wiki_schema_reader, "parse_rules_table", broken)
        registry = wiki_schema_reader.load_registry(tmp_path)
        assert registry.rules == []
        _assert_noted("wiki_schema_reader.rules_parse", "rules table broke")


class TestWikiStoreTolerantSync:
    def test_strict_failure_degrades_to_none_and_is_logged(self, monkeypatch, tmp_path):
        from mcp_server.infrastructure import wiki_store

        def broken(root, **kwargs):
            raise RuntimeError("sync broke")

        monkeypatch.setattr(wiki_store, "sync_memory_strict", broken)
        out = wiki_store.sync_memory(
            tmp_path, memory_id=1, content="c", tags=[], domain="d"
        )
        assert out is None
        _assert_noted("wiki_store.sync_memory", "sync broke")


class TestPipelineDiscoveryProbe:
    def test_registry_read_failure_is_logged_and_reports_not_installed(
        self, caplog, monkeypatch
    ):
        from mcp_server.infrastructure import pipeline_discovery

        def broken(path):
            raise RuntimeError("registry corrupt")

        monkeypatch.setattr(pipeline_discovery, "read_json", broken)
        with caplog.at_level(
            "DEBUG", logger="mcp_server.infrastructure.pipeline_discovery"
        ):
            assert pipeline_discovery._marketplace_pipeline_binary() is None
        assert any("AP plugin discovery failed" in r.message for r in caplog.records)


class TestWorkflowAstGraphSkips:
    def _source(self):
        from mcp_server.infrastructure.workflow_graph_source_ast import (
            WorkflowGraphASTSource,
        )

        return WorkflowGraphASTSource.__new__(WorkflowGraphASTSource)

    def test_symbol_batch_failure_skips_graph_and_is_logged(self, caplog):
        src = self._source()

        async def broken(gp, paths):
            raise RuntimeError("corrupt graph")
            yield  # pragma: no cover — makes this an async generator

        src._symbol_batches_async = broken

        async def collect():
            return [b async for b in src._iter_symbols_async(["g1"], ["p"])]

        with caplog.at_level(
            "DEBUG", logger="mcp_server.infrastructure.workflow_graph_source_ast"
        ):
            assert asyncio.run(collect()) == []
        assert any(
            "symbol batches failed for graph g1" in r.message for r in caplog.records
        )

    def test_edge_batch_failure_skips_graph_and_is_logged(self, caplog):
        src = self._source()

        async def broken(gp, paths):
            raise RuntimeError("corrupt graph")
            yield  # pragma: no cover — makes this an async generator

        src._edge_batches_async = broken

        async def collect():
            return [b async for b in src._iter_edges_async(["g1"], ["p"])]

        with caplog.at_level(
            "DEBUG", logger="mcp_server.infrastructure.workflow_graph_source_ast"
        ):
            assert asyncio.run(collect()) == []
        assert any(
            "edge batches failed for graph g1" in r.message for r in caplog.records
        )


class TestNarrowedSqliteGuards:
    """Typed-narrow contract checks: a sqlite3.Error still degrades to the
    documented no-op value, while a non-DB error now propagates (the
    narrowing is the behaviour change BLE001 buys)."""

    def _store_with_broken_conn(self, exc):
        from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

        store = SqliteMemoryStore.__new__(SqliteMemoryStore)
        conn = MagicMock()
        conn.execute.side_effect = exc
        store._conn = conn
        return store

    def test_signature_stats_sqlite_error_degrades_to_zero(self):
        import sqlite3

        store = self._store_with_broken_conn(sqlite3.OperationalError("no column"))
        assert store.signature_repeat_stats("sig") == (0, None)

    def test_signature_stats_programming_bug_now_propagates(self):
        store = self._store_with_broken_conn(TypeError("bad bind"))
        with pytest.raises(TypeError):
            store.signature_repeat_stats("sig")

    def test_extinction_count_sqlite_error_degrades_to_zero(self):
        import sqlite3

        store = self._store_with_broken_conn(sqlite3.OperationalError("no column"))
        assert store.extinguished_count(threshold=0.5) == 0
