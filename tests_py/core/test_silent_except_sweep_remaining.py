"""Silent-except sweep (audit 2026-07-11): remaining Class A call sites not
already covered by a dedicated test module (test_reranker.py,
test_write_gate.py, test_pg_recall_silent_failures.py,
test_recall_silent_failures.py). Each test proves the pre-existing
fallback is unchanged AND now observable via
``mcp_server.observability.silent_failure``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.observability import silent_failure
from tests_py.conftest import requires_psycopg  # type: ignore


@pytest.fixture(autouse=True)
def _reset():
    silent_failure.reset()
    yield
    silent_failure.reset()


WARN_LOGGER = "mcp_server.observability.silent_failure"


class TestRetrievalDispatchFailuresAreObservable:
    def test_multihop_failure_is_logged(self, caplog, monkeypatch):
        from mcp_server.core import retrieval_dispatch

        monkeypatch.setattr(
            retrieval_dispatch,
            "decompose_query",
            lambda q: {"sub_queries": ["sub one", "sub two"]},
        )

        def broken_hop(q):
            raise RuntimeError("hop failed")

        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            results, tier = retrieval_dispatch.dispatch_retrieval(
                query="a b multi-hop",
                signals={"vector": [(1, 0.9)]},
                intent_info={"intent": "multi_hop", "weights": {}},
                content_lookup={},
                hop_fn=broken_hop,
            )
        assert tier == "mixed"
        assert any("retrieval_dispatch.multihop" in r.message for r in caplog.records)

    def test_rerank_wrapper_failure_is_logged(self, caplog, monkeypatch):
        from mcp_server.core import retrieval_dispatch

        def broken_rerank(query, pool, content_lookup):
            raise RuntimeError("content_lookup malformed")

        monkeypatch.setattr(retrieval_dispatch, "rerank_results", broken_rerank)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            results, tier = retrieval_dispatch.dispatch_retrieval(
                query="q",
                signals={"vector": [(1, 0.9)]},
                intent_info={"intent": "general", "weights": {}},
                content_lookup={1: "text"},
            )
        assert any(
            "retrieval_dispatch.rerank_wrapper" in r.message for r in caplog.records
        )


class TestRetrievalSignalsFailuresAreObservable:
    def test_hopfield_failure_is_logged(self, caplog):
        from mcp_server.core.retrieval_signals import compute_hopfield_hdc

        store = MagicMock()
        store.get_hot_embeddings.side_effect = RuntimeError("pg down")
        settings = MagicMock(HOPFIELD_BETA=1.0)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            hop, hdc = compute_hopfield_hdc(
                query="q",
                q_emb=[0.1, 0.2],
                store=store,
                embeddings=MagicMock(dimensions=2),
                hot_mems=[],
                settings=settings,
                pool=5,
                min_heat=0.05,
            )
        assert hop == []
        assert any("retrieval_signals.hopfield" in r.message for r in caplog.records)

    def test_successor_representation_failure_is_logged(self, caplog):
        from mcp_server.core.retrieval_signals import compute_graph_signals

        store = MagicMock()
        store.get_temporal_co_access.side_effect = RuntimeError("pg down")
        store.spread_activation_memories.return_value = []
        settings = MagicMock(
            SA_DECAY=0.5, SA_THRESHOLD=0.1, SA_MAX_DEPTH=2, SA_MAX_NODES=10
        )
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            sr, sa = compute_graph_signals(
                query="q",
                store=store,
                vec_results=[(1, 0.9)],
                min_heat=0.05,
                settings=settings,
                pool=5,
            )
        assert sr == []
        assert any(
            "retrieval_signals.successor_representation" in r.message
            for r in caplog.records
        )


class TestWritePostStoreFailuresAreObservable:
    def test_synaptic_tagging_failure_is_logged(self, caplog):
        from mcp_server.core.write_post_store import run_synaptic_tagging

        store = MagicMock()
        store.get_hot_memories.side_effect = RuntimeError("pg down")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            tagged = run_synaptic_tagging(
                mem_id=1, importance=0.9, new_entity_names=["X"], store=store
            )
        assert tagged == []
        assert any(
            "write_post_store.synaptic_tagging" in r.message for r in caplog.records
        )

    def test_engram_allocation_failure_is_logged(self, caplog):
        from mcp_server.core.write_post_store import allocate_engram_slot

        store = MagicMock()
        store.init_engram_slots.side_effect = RuntimeError("pg down")
        settings = MagicMock(HOPFIELD_MAX_PATTERNS=500, EXCITABILITY_HALF_LIFE_HOURS=24)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            result = allocate_engram_slot(mem_id=1, settings=settings, store=store)
        assert result is None
        assert any(
            "write_post_store.engram_allocation" in r.message for r in caplog.records
        )


class TestMemoryIngestFailuresAreObservable:
    def test_entity_extraction_failure_is_logged(self, caplog, monkeypatch):
        from mcp_server.core import memory_ingest

        store = MagicMock()
        store.insert_memory.return_value = 42

        def broken_extract(content):
            raise RuntimeError("NER model unavailable")

        monkeypatch.setattr(
            "mcp_server.core.knowledge_graph.extract_entities", broken_extract
        )
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            ids = memory_ingest.ingest_memory(
                {"content": "some episodic memory text"},
                store=store,
                embeddings=MagicMock(),
                decompose=False,
            )
        assert ids == [42]
        assert any(
            "memory_ingest.entity_extraction" in r.message for r in caplog.records
        )


@requires_psycopg
class TestPgStoreFailuresAreObservable:
    def test_update_memory_value_failure_is_logged(self, caplog):
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        store = object.__new__(PgMemoryStore)
        store._execute = MagicMock(side_effect=RuntimeError("no such column"))
        store._conn = MagicMock()
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            store.update_memory_value(1, 0.5)
        assert any("pg_store.update_memory_value" in r.message for r in caplog.records)

    def test_update_memory_extinction_failure_is_logged(self, caplog):
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        store = object.__new__(PgMemoryStore)
        store._execute = MagicMock(side_effect=RuntimeError("no such column"))
        store._conn = MagicMock()
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            store.update_memory_extinction(1, 0.5)
        assert any(
            "pg_store.update_memory_extinction" in r.message for r in caplog.records
        )
