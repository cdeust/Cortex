"""S110 sweep (issue #197, first family): handler-layer try/except/pass sites.

Each test forces the guarded operation to fail and asserts the
now-visible ``silent_failure`` signal AND that the pre-existing fallback
behaviour is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
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
    """Exact-component check via silent_failure.status().

    The caplog asserts pin that a WARNING was emitted; this pins the exact
    component name and that the real exception (not None) was recorded —
    the two mutants a substring-in-message assert lets survive
    (mutation run, scripts/mutation_check.sh, 2026-07-28).
    """
    status = silent_failure.status()
    assert component in status
    assert error_text in str(status[component]["last_error"])


class TestDoctorBackendResolution:
    def test_resolution_failure_falls_back_to_pg_checks_and_is_logged(
        self, caplog, monkeypatch
    ):
        from mcp_server import doctor

        def broken(environ):
            raise RuntimeError("marker unreadable")

        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(doctor, "effective_backend", broken)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            checks = doctor.active_checks()
        assert checks is doctor.CHECKS
        assert any("doctor.backend_resolution" in r.message for r in caplog.records)
        _assert_noted("doctor.backend_resolution", "marker unreadable")


class TestBackfillConceptLink:
    def test_relationship_failure_skips_link_and_is_logged(self, caplog, monkeypatch):
        from mcp_server.handlers import backfill_helpers

        monkeypatch.setattr(
            backfill_helpers, "_upsert_concept_entity", lambda store, c: 5
        )
        store = MagicMock()
        store.insert_relationship.side_effect = RuntimeError("constraint")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            linked = backfill_helpers.link_concepts(store, 1, ["alpha"])
        assert linked == 0
        assert any("backfill.concept_link" in r.message for r in caplog.records)
        _assert_noted("backfill.concept_link", "constraint")


class TestBackfillCascadeAdvancement:
    def test_cascade_failure_is_logged_and_result_unpoisoned(self, caplog, monkeypatch):
        from mcp_server.handlers import backfill_memories

        def broken(store):
            raise RuntimeError("cascade broke")

        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(backfill_memories, "run_cascade_advancement", broken)
        result = {"backfilled": 3}
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            backfill_memories._advance_cascade(MagicMock(), result)
        assert "cascade_advanced" not in result
        assert any("backfill.cascade_advancement" in r.message for r in caplog.records)
        _assert_noted("backfill.cascade_advancement", "cascade broke")

    def test_cascade_success_records_advanced_count(self, monkeypatch):
        from mcp_server.handlers import backfill_memories

        monkeypatch.setattr(
            backfill_memories,
            "run_cascade_advancement",
            lambda store: {"advanced": 2},
        )
        result = {"backfilled": 3}
        backfill_memories._advance_cascade(MagicMock(), result)
        assert result["cascade_advanced"] == 2

    def test_nothing_backfilled_skips_cascade(self, monkeypatch):
        from mcp_server.handlers import backfill_memories

        called = MagicMock()
        monkeypatch.setattr(backfill_memories, "run_cascade_advancement", called)
        result = {"backfilled": 0}
        backfill_memories._advance_cascade(MagicMock(), result)
        called.assert_not_called()
        assert "cascade_advanced" not in result


class TestChangeImpactHeatBump:
    def test_update_failure_skips_bump_and_is_logged(self, caplog):
        from mcp_server.handlers.change_impact import _apply_heat_bumps

        store = MagicMock()
        store.get_memory.return_value = {"heat_base": 0.5}
        store.update_memory_heat.side_effect = RuntimeError("pg down")
        matches = [SimpleNamespace(memory_id="1")]
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            bumped = _apply_heat_bumps(store, matches, 0.1)
        assert bumped == 0
        assert any("change_impact.heat_bump" in r.message for r in caplog.records)
        _assert_noted("change_impact.heat_bump", "pg down")


class TestCodebaseAnalyzeSites:
    def test_semantic_promotion_failure_is_logged(self, caplog):
        from mcp_server.handlers.codebase_analyze import _set_memory_metadata

        store = MagicMock()
        store.acquire_batch.side_effect = RuntimeError("pool closed")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            _set_memory_metadata(store, 1)
        assert any(
            "codebase_analyze.semantic_promotion" in r.message for r in caplog.records
        )
        _assert_noted("codebase_analyze.semantic_promotion", "pool closed")

    def test_import_edge_failure_is_logged(self, caplog, monkeypatch):
        from mcp_server.handlers import codebase_analyze_helpers as helpers

        monkeypatch.setattr(
            helpers, "_get_or_create_entity", lambda store, name, kind, domain: 1
        )
        store = MagicMock()
        store.insert_relationship.side_effect = RuntimeError("constraint")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            count = helpers.persist_file_edge(store, [("a.py", "b.py")], "dom")
        assert count == 0
        assert any("codebase_analyze.import_edge" in r.message for r in caplog.records)
        _assert_noted("codebase_analyze.import_edge", "constraint")

    def test_extends_edge_failure_is_logged(self, caplog, monkeypatch):
        from mcp_server.handlers import codebase_analyze_helpers as helpers

        monkeypatch.setattr(
            helpers, "_get_or_create_entity", lambda store, name, kind, domain: 1
        )
        store = MagicMock()
        store.insert_relationship.side_effect = RuntimeError("constraint")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            count = helpers.persist_inheritance_edge(store, [("Child", "Base")], "dom")
        assert count == 0
        assert any("codebase_analyze.extends_edge" in r.message for r in caplog.records)
        _assert_noted("codebase_analyze.extends_edge", "constraint")

    @staticmethod
    def _store_with_broken_conn():
        store = MagicMock()
        conn = MagicMock()
        conn.execute.side_effect = RuntimeError("sql broke")
        store.acquire_batch.return_value.__enter__.return_value = conn
        return store

    def test_god_node_tag_failure_is_logged(self, caplog):
        from mcp_server.handlers.codebase_analyze_helpers import persist_god_node_tags

        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            persist_god_node_tags(self._store_with_broken_conn(), ["a.py"])
        assert any("codebase_analyze.god_node_tag" in r.message for r in caplog.records)
        _assert_noted("codebase_analyze.god_node_tag", "sql broke")

    def test_community_tag_failure_is_logged(self, caplog):
        from mcp_server.handlers.codebase_analyze_helpers import persist_community_tags

        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            persist_community_tags(self._store_with_broken_conn(), {"a.py": 1})
        assert any(
            "codebase_analyze.community_tag" in r.message for r in caplog.records
        )
        _assert_noted("codebase_analyze.community_tag", "sql broke")


class TestConsolidationSites:
    def test_stage_timestamp_failure_is_logged(self, caplog):
        from mcp_server.handlers.consolidation.cascade import _update_stage_entered

        store = MagicMock()
        store.acquire_batch.side_effect = RuntimeError("pool closed")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            _update_stage_entered(store, 1, datetime.now(timezone.utc))
        assert any("consolidation.stage_timestamp" in r.message for r in caplog.records)
        _assert_noted("consolidation.stage_timestamp", "pool closed")

    def test_source_root_failure_returns_none_and_is_logged(self, caplog, monkeypatch):
        # drain_operations no longer back-imports headless_authoring at
        # module scope (issue #237) — importing it standalone is safe now.
        from mcp_server.handlers.consolidation import drain_operations
        from mcp_server.handlers.consolidation.drain_operations import (
            _optional_source_root,
        )

        def broken(domain):
            raise RuntimeError("no source map")

        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(drain_operations, "_project_source_root", broken)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            assert _optional_source_root({"domain": "cortex"}) is None
        assert any(
            "consolidation.project_source_root" in r.message for r in caplog.records
        )
        _assert_noted("consolidation.project_source_root", "no source map")

    def test_source_root_missing_domain_is_silent(self, caplog):
        # drain_operations no longer back-imports headless_authoring at
        # module scope (issue #237) — importing it standalone is safe now.
        from mcp_server.handlers.consolidation.drain_operations import (
            _optional_source_root,
        )

        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            assert _optional_source_root({}) is None
        assert not caplog.records

    def test_memify_prune_failure_is_logged(self, caplog):
        from mcp_server.handlers.consolidation.memify import _stream_prune_strengthen

        store = MagicMock()
        store.delete_memory.side_effect = RuntimeError("pg down")
        prunable = {"id": 1, "heat": 0.0, "confidence": 0.0, "access_count": 0}
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            pruned, strengthened, _flags, scanned = _stream_prune_strengthen(
                store, [prunable]
            )
        assert (pruned, strengthened, scanned) == (0, 0, 1)
        assert any("consolidation.memify_prune" in r.message for r in caplog.records)
        _assert_noted("consolidation.memify_prune", "pg down")

    def test_memify_strengthen_failure_is_logged(self, caplog):
        from mcp_server.handlers.consolidation.memify import _stream_prune_strengthen

        store = MagicMock()
        store.update_memory_importance.side_effect = RuntimeError("pg down")
        strengtheneable = {
            "id": 2,
            "heat": 0.9,
            "confidence": 0.9,
            "access_count": 9,
            "importance": 0.5,
        }
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            pruned, strengthened, _flags, scanned = _stream_prune_strengthen(
                store, [strengtheneable]
            )
        assert (pruned, strengthened, scanned) == (0, 0, 1)
        assert any(
            "consolidation.memify_strengthen" in r.message for r in caplog.records
        )
        _assert_noted("consolidation.memify_strengthen", "pg down")


class TestRebuildProfilesFreshnessCheck:
    def test_malformed_timestamp_degrades_to_rebuild_and_is_logged(
        self, caplog, monkeypatch
    ):
        from mcp_server.handlers import rebuild_profiles

        monkeypatch.setattr(
            rebuild_profiles,
            "load_profiles",
            lambda: {"updatedAt": "not-a-timestamp", "domains": {"d": {}}},
        )
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            assert rebuild_profiles._check_skip(force=False) is None
        assert any(
            "rebuild_profiles.freshness_check" in r.message for r in caplog.records
        )
        _assert_noted("rebuild_profiles.freshness_check", "not-a-timestamp")


class TestRememberCurationDedup:
    def test_search_failure_degrades_to_create_and_is_logged(self, caplog):
        from mcp_server.handlers.remember_helpers import try_curation

        store = MagicMock()
        store.search_vectors.side_effect = RuntimeError("vector index gone")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            action, target = try_curation(
                "content", [0.1, 0.2], False, store, MagicMock(), [], 0.5
            )
        assert (action, target) == ("create", None)
        assert any(
            "remember_helpers.curation_dedup" in r.message for r in caplog.records
        )
        _assert_noted("remember_helpers.curation_dedup", "vector index gone")


class TestUpdateStageEnteredHappyPath:
    def test_stamp_writes_the_expected_update(self):
        """Pins the SQL and parameter order (mutation-run survivors on the
        happy path: scripts/mutation_check.sh, 2026-07-28)."""
        from mcp_server.handlers.consolidation.cascade import _update_stage_entered

        store = MagicMock()
        conn = MagicMock()
        store.acquire_batch.return_value.__enter__.return_value = conn
        now = datetime(2026, 7, 28, tzinfo=timezone.utc)
        _update_stage_entered(store, 42, now)
        conn.execute.assert_called_once_with(
            "UPDATE memories SET stage_entered_at = %s WHERE id = %s",
            (now, 42),
        )
