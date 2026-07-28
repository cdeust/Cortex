"""BLE001 sweep (issue #197, second family): handler-layer sites that
gained a ``silent_failure`` signal.

Each test forces the guarded operation to fail and asserts the
now-visible ``silent_failure`` signal AND that the pre-existing fallback
behaviour is unchanged (same contract as test_s110_sweep_handlers.py).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

# Imported before candidate_scan anywhere in this module: candidate_scan
# and headless_authoring are mutually importing; headless_authoring must
# initialize first (matching the package's own import order).
import mcp_server.handlers.consolidation.headless_authoring  # noqa: F401, E402
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


class TestAssessCoverageEntityDensity:
    def test_entity_fetch_failure_degrades_to_zero_and_is_logged(self):
        from mcp_server.handlers.assess_coverage import _entity_density

        store = MagicMock()
        store.get_all_entities.side_effect = RuntimeError("entities table gone")
        out = _entity_density([{"id": 1}], store)
        assert out == {"avg_entities_per_memory": 0.0, "total_entities": 0}
        _assert_noted("assess_coverage.entity_density", "entities table gone")


class TestAutoTaskRecordRecentMemories:
    def test_fetch_failure_degrades_to_empty_and_is_logged(self):
        from mcp_server.handlers.auto_task_record_writer import _session_memories

        store = MagicMock()
        store.get_recently_accessed_memories.side_effect = RuntimeError("pg down")
        assert _session_memories(store, "s1", "dom") == []
        _assert_noted("auto_task_record.recent_memories", "pg down")


class TestBackfillArtifactStore:
    def test_artifact_failure_keeps_full_content_and_is_logged(self, monkeypatch):
        from mcp_server.handlers.backfill_helpers import gist_oversized_content
        from mcp_server.infrastructure import artifact_store

        def broken(content):
            raise RuntimeError("disk full")

        monkeypatch.setattr(artifact_store, "store_artifact", broken)
        content = "x" * 20_000
        assert gist_oversized_content(content) == content
        _assert_noted("backfill.artifact_store", "disk full")


class TestBackfillConceptEntityUpsert:
    def test_insert_failure_degrades_to_none_and_is_logged(self):
        from mcp_server.handlers.backfill_helpers import _upsert_concept_entity

        store = MagicMock()
        store.get_entity_by_name.return_value = None
        store.insert_entity.side_effect = RuntimeError("constraint")
        assert _upsert_concept_entity(store, "solid") is None
        _assert_noted("backfill.concept_entity_upsert", "constraint")


class TestBackfillPreview:
    def test_preview_failure_degrades_to_none_and_is_logged(
        self, monkeypatch, tmp_path
    ):
        from mcp_server.handlers import backfill_memories

        def broken(path):
            raise RuntimeError("extractor broke")

        monkeypatch.setattr(backfill_memories, "read_head_tail", broken)
        out = backfill_memories._build_dry_run_preview(
            tmp_path / "s.jsonl", "slug", 0.5
        )
        assert out is None
        _assert_noted("backfill.preview", "extractor broke")


class TestChangeImpactMemoryRead:
    def test_read_failure_skips_bump_and_is_logged(self):
        from mcp_server.handlers.change_impact import _apply_heat_bumps

        store = MagicMock()
        store.get_memory.side_effect = RuntimeError("pg down")
        matches = [SimpleNamespace(memory_id="1")]
        assert _apply_heat_bumps(store, matches, 0.1) == 0
        store.update_memory_heat.assert_not_called()
        _assert_noted("change_impact.memory_read", "pg down")


class TestAuthoringPromptsLiveGapAudit:
    def test_audit_failure_falls_back_to_frozen_gaps_and_is_logged(self, monkeypatch):
        from mcp_server.core import wiki_curation_gaps
        from mcp_server.handlers.consolidation.authoring_prompts import (
            _live_audit_gaps,
        )

        def broken(body):
            raise RuntimeError("section catalogue broke")

        monkeypatch.setattr(wiki_curation_gaps, "missing_sections", broken)
        assert _live_audit_gaps("body", ["overview"]) == ["overview"]
        _assert_noted("authoring_prompts.live_gap_audit", "section catalogue broke")


class TestCandidateScanSites:
    def test_live_audit_failure_skips_page_and_is_logged(self, monkeypatch, tmp_path):
        from mcp_server.core import wiki_curation_gaps
        from mcp_server.handlers.consolidation.candidate_scan import (
            _scan_pages_with_gaps,
        )

        page = tmp_path / "cortex" / "thing.md"
        page.parent.mkdir(parents=True)
        page.write_text(
            "---\nkind: reference\nsource_file_path: src/x.py\n---\nbody\n",
            encoding="utf-8",
        )

        def broken(body):
            raise RuntimeError("audit broke")

        monkeypatch.setattr(wiki_curation_gaps, "missing_sections", broken)
        assert _scan_pages_with_gaps(tmp_path) == []
        _assert_noted("candidate_scan.live_audit", "audit broke")

    def test_registry_failure_degrades_to_no_candidates_and_is_logged(
        self, monkeypatch, tmp_path
    ):
        from mcp_server.handlers.consolidation.candidate_scan import (
            _collect_anchor_candidates,
        )
        from mcp_server.shared import domain_mapping

        def broken():
            raise RuntimeError("registry unreadable")

        monkeypatch.setattr(domain_mapping, "_build_registry", broken)
        assert _collect_anchor_candidates(tmp_path, 3) == []
        _assert_noted("candidate_scan.registry", "registry unreadable")

    def test_audit_domain_failure_skips_domain_and_is_logged(
        self, monkeypatch, tmp_path
    ):
        from mcp_server.core import wiki_coverage
        from mcp_server.handlers.consolidation.candidate_scan import (
            _collect_anchor_candidates,
        )
        from mcp_server.shared import domain_mapping

        registry = SimpleNamespace(repos=[SimpleNamespace(canonical="d1")])
        monkeypatch.setattr(domain_mapping, "_build_registry", lambda: registry)
        monkeypatch.setattr(
            wiki_coverage, "_project_source_root", lambda d: str(tmp_path)
        )

        def broken(root, domain):
            raise RuntimeError("audit broke")

        monkeypatch.setattr(wiki_coverage, "audit_domain", broken)
        assert _collect_anchor_candidates(tmp_path, 3) == []
        _assert_noted("candidate_scan.audit_domain", "audit broke")


class TestClsClusterCount:
    def test_cluster_failure_reports_zero_and_is_logged(self, monkeypatch):
        from mcp_server.handlers.consolidation import cls as cls_mod

        def broken(episodic, similarity_fn, threshold):
            raise RuntimeError("clustering broke")

        monkeypatch.setattr(cls_mod, "cluster_by_similarity", broken)
        out = cls_mod._count_multi_member_clusters([{"id": 1}], MagicMock())
        assert out == 0
        _assert_noted("cls.cluster_count", "clustering broke")


class TestMemifyReweight:
    def test_entity_fetch_failure_reports_zero_and_is_logged(self):
        from mcp_server.handlers.consolidation.memify import _reweight_relationships

        store = MagicMock()
        store.get_all_entities.side_effect = RuntimeError("pg down")
        assert _reweight_relationships(store) == 0
        _assert_noted("memify.relationship_reweight", "pg down")


class TestMemifyDeriveSites:
    def test_marker_fetch_failure_degrades_to_empty_set_and_is_logged(self):
        from mcp_server.handlers.consolidation.memify_derive import (
            _existing_derived_markers,
        )

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        assert _existing_derived_markers(store) == set()
        _assert_noted("memify_derive.derived_markers", "tag query broke")

    def test_provenance_fetch_failure_degrades_to_empty_and_is_logged(self):
        from mcp_server.handlers.consolidation.memify_derive import (
            _provenance_memory_ids,
        )

        store = MagicMock()
        store.get_memories_for_entity.side_effect = RuntimeError("pg down")
        rel = {"source_entity_id": 1, "target_entity_id": 2}
        assert _provenance_memory_ids(store, rel) == []
        _assert_noted("memify_derive.provenance_memories", "pg down")


class TestCurateWikiUncited:
    def test_store_failure_degrades_to_empty_report_and_is_logged(self, monkeypatch):
        from mcp_server.handlers import curate_wiki_uncited

        def broken():
            raise RuntimeError("store down")

        monkeypatch.setattr(curate_wiki_uncited, "get_shared_store", broken)
        out = curate_wiki_uncited.report_uncited_deliberate(5)
        assert out["candidates"] == []
        assert out["candidate_count"] == 0
        _assert_noted("curate_wiki_uncited.candidates", "store down")


class TestDetectGapsBlindSpots:
    def test_profile_failure_degrades_to_no_gaps_and_is_logged(self, monkeypatch):
        from mcp_server.handlers import detect_gaps

        def broken():
            raise RuntimeError("profiles unreadable")

        monkeypatch.setattr(detect_gaps, "load_profiles", broken)
        assert detect_gaps._cognitive_style_gaps(None) == []
        _assert_noted("detect_gaps.blind_spots", "profiles unreadable")


class TestIngestTagLookupSites:
    """The four duck-typed get_memories_by_tag readers share one contract:
    a failing tag query degrades to 'not found' — now observably."""

    def test_docs_content_find_existing_failure_is_logged(self):
        from mcp_server.handlers.ingest_docs_content_writers import (
            find_existing_doc_memory,
        )

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        assert find_existing_doc_memory(store, "dom", "a/b.md") is None
        _assert_noted("ingest_docs_content.find_existing_doc", "tag query broke")

    def test_document_already_ingested_failure_is_logged(self):
        from mcp_server.handlers.ingest_document_writers import already_ingested

        store = MagicMock()
        store.get_memories_by_tag.side_effect = RuntimeError("tag query broke")
        prov = MagicMock()
        prov.dedup_tag.return_value = "doc:tag"
        assert already_ingested(store, prov) is None
        _assert_noted("ingest_document.already_ingested", "tag query broke")

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
