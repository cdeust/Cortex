"""Unit tests for handlers.consolidation.wiki_maintenance's G-2 grooming
wiring (2026-07-11): the citation-seed reconciliation call and its
apply/limit knobs.

Monkeypatch-based, no DB required — mirrors
``tests_py/handlers/test_lesson_promotion.py``'s contract-shape style.
Each sub-pass this module orchestrates (purge axes, dashboards, source/
domain backfill, backlog) already has its own dedicated test file; this
file covers only the NEW wiring added for the citation-seed pass so it
doesn't need to re-mock the whole orchestration surface.
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers.consolidation import wiki_maintenance
from mcp_server.infrastructure import memory_store
from mcp_server.infrastructure.memory_config import get_memory_settings


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeStore:
    """Stand-in store; every sub-pass below is monkeypatched so this
    object's shape never actually matters to the passes it's threaded
    through. Carries ``batch_pool`` so ``run_wiki_maintenance``'s own
    backend gate (issue #636) treats it as PostgreSQL-backed and
    actually invokes the mocked PG-only passes below -- without this,
    the four PG-only stanzas would never be wired in these tests at
    all, since gating now happens once, at the top of the function,
    not per pass."""

    batch_pool = object()


class _FakeSqliteStore:
    """Stand-in store with no ``batch_pool`` -- the SQLite shape."""


def _silence_everything_except_citation_seed(monkeypatch) -> None:
    """Make every OTHER axis a cheap no-op so this test isolates the
    citation-seed wiring instead of exercising the full orchestration
    surface (each of those axes has its own dedicated test file)."""

    async def _noop_purge(args):
        return {"purged": 0, "deferred": 0, "placeholder_lines_purged": 0}

    monkeypatch.setattr(wiki_maintenance, "_invoke_wiki_purge", _noop_purge)

    def _noop_dashboards(_root):
        return {}

    # All patches below target wiki_maintenance's own bindings — the
    # imports are at module top (#197 family 4), so patching the defining
    # modules would no longer reach the bound references.
    monkeypatch.setattr(wiki_maintenance, "write_dashboards", _noop_dashboards)

    async def _noop_source_backfill(store, *, apply):
        return {"pages_scanned": 0, "primaries_written": 0, "status": "ok"}

    monkeypatch.setattr(
        wiki_maintenance, "run_source_backfill_pass", _noop_source_backfill
    )

    async def _noop_domain_backfill(store, *, apply):
        return {"pages_scanned": 0, "domains_reassigned": 0, "status": "ok"}

    monkeypatch.setattr(
        wiki_maintenance, "run_domain_backfill_pass", _noop_domain_backfill
    )

    async def _noop_backlog(store):
        return {
            "cluster_jobs": 0,
            "coverage_gaps": 0,
            "uncovered_files": 0,
            "drifted_pages": 0,
            "pending_total": 0,
        }

    monkeypatch.setattr(wiki_maintenance, "run_backlog_pass", _noop_backlog)
    monkeypatch.setattr(wiki_maintenance, "_lesson_promotion_backlog", lambda store: 7)


class TestCitationSeedWiring:
    def test_apply_and_limit_threaded_through(self, monkeypatch) -> None:
        _silence_everything_except_citation_seed(monkeypatch)
        seen: dict = {}

        async def _fake_seed_pass(store, *, apply, limit):
            seen["apply"] = apply
            seen["limit"] = limit
            return {
                "scanned_rows": 3,
                "seeded": 1,
                "already_cited": 2,
                "skipped_race": 0,
                "journal": [],
                "status": "ok",
            }

        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            wiki_maintenance,
            "run_wiki_citation_seed_pass",
            _fake_seed_pass,
        )

        result = _run(
            wiki_maintenance.run_wiki_maintenance(
                _FakeStore(),
                apply_citation_seed=False,
                citation_seed_limit=42,
                max_purges_per_axis=None,
            )
        )

        assert seen["apply"] is False
        assert seen["limit"] == 42
        assert result["citation_seed"]["seeded"] == 1
        assert result["status"] == "ok"

    def test_default_limit_falls_back_to_module_constant(self, monkeypatch) -> None:
        _silence_everything_except_citation_seed(monkeypatch)
        seen: dict = {}

        async def _fake_seed_pass(store, *, apply, limit):
            seen["limit"] = limit
            return {"status": "ok", "journal": []}

        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            wiki_maintenance,
            "run_wiki_citation_seed_pass",
            _fake_seed_pass,
        )

        _run(
            wiki_maintenance.run_wiki_maintenance(
                _FakeStore(), citation_seed_limit=None, max_purges_per_axis=None
            )
        )

        from mcp_server.handlers.consolidation.wiki_citation_seed_pass import (
            DEFAULT_SEED_SCAN_LIMIT,
        )

        assert seen["limit"] == DEFAULT_SEED_SCAN_LIMIT

    def test_citation_seed_failure_is_non_fatal(self, monkeypatch) -> None:
        """A blown-up citation-seed pass must degrade the SAME way every
        other axis in this module already does — never take down the
        whole consolidate cycle (Move 4: symptom vs. cause; this is
        infra protecting the caller, not silencing a real bug)."""
        _silence_everything_except_citation_seed(monkeypatch)

        async def _boom(store, *, apply, limit):
            raise RuntimeError("PG connection reset")

        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            wiki_maintenance,
            "run_wiki_citation_seed_pass",
            _boom,
        )

        result = _run(
            wiki_maintenance.run_wiki_maintenance(
                _FakeStore(), max_purges_per_axis=None
            )
        )

        assert "error" in result["citation_seed"]["status"]
        assert result["status"].startswith("citation_seed_error")
        # Non-fatal: the function still returned a full dict, not raised.
        assert "pending_total" in result


class TestLessonPromotionBacklogEscalation:
    """#636 follow-up: a real query failure for lesson_promotion_backlog
    must escalate ``out["status"]`` the same way the other three
    PostgreSQL-only passes do, not degrade to a silent ``None`` with
    ``status`` left ``ok``."""

    def test_failure_escalates_status(self, monkeypatch) -> None:
        _silence_everything_except_citation_seed(monkeypatch)

        async def _fake_seed_pass(store, *, apply, limit):
            return {"status": "ok", "journal": []}

        monkeypatch.setattr(
            wiki_maintenance, "run_wiki_citation_seed_pass", _fake_seed_pass
        )

        def _boom(store):
            raise RuntimeError("PG connection reset")

        monkeypatch.setattr(wiki_maintenance, "_lesson_promotion_backlog", _boom)

        result = _run(
            wiki_maintenance.run_wiki_maintenance(
                _FakeStore(), max_purges_per_axis=None
            )
        )

        assert result["lesson_promotion_backlog"] is None
        assert result["status"].startswith("lesson_promotion_backlog_error")


class TestPgOnlyStanzasGatedOnce:
    """#636: the four PG-only stanzas (source_backfill, domain_backfill,
    citation_seed, lesson_promotion_backlog) are wired once, at the top
    of ``run_wiki_maintenance``, from whether ``store`` has
    ``batch_pool`` -- not defended against per pass. On a store without
    it they are absent from the response, never a "skipped" status."""

    def test_absent_on_a_store_without_batch_pool(self, monkeypatch) -> None:
        _silence_everything_except_citation_seed(monkeypatch)

        result = _run(
            wiki_maintenance.run_wiki_maintenance(
                _FakeSqliteStore(), max_purges_per_axis=None
            )
        )

        assert "source_backfill" not in result
        assert "domain_backfill" not in result
        assert "citation_seed" not in result
        assert "lesson_promotion_backlog" not in result
        assert result["status"] == "ok"

    def test_present_on_a_store_with_batch_pool(self, monkeypatch) -> None:
        _silence_everything_except_citation_seed(monkeypatch)

        async def _fake_seed_pass(store, *, apply, limit):
            return {"status": "ok", "journal": []}

        monkeypatch.setattr(
            wiki_maintenance, "run_wiki_citation_seed_pass", _fake_seed_pass
        )

        result = _run(
            wiki_maintenance.run_wiki_maintenance(
                _FakeStore(), max_purges_per_axis=None
            )
        )

        assert result["source_backfill"]["status"] == "ok"
        assert result["domain_backfill"]["status"] == "ok"
        assert result["citation_seed"]["status"] == "ok"
        assert result["lesson_promotion_backlog"] == 7


def _no_stanza_errored(result: dict, path: str = "") -> None:
    """Recursively assert no ``status`` field anywhere in the result
    starts with ``error:`` -- issue #636's own requested contract check."""
    for key, value in result.items():
        here = f"{path}.{key}" if path else key
        if key == "status" and isinstance(value, str):
            assert not value.startswith("error:"), f"{here} = {value!r}"
        elif isinstance(value, dict):
            _no_stanza_errored(value, here)


class TestRealSqliteStoreContract:
    """#636's own requested check: run the whole cycle against a real
    store built through get_shared_store's actual backend-selection path
    (not a direct SqliteMemoryStore(...) construction, which would skip
    that selection logic -- exactly what this bug was about), and prove
    the PG-only passes are never reached (no AttributeError disguised as
    a stanza status)."""

    def test_no_stanza_errors_and_pg_only_keys_are_absent(
        self, tmp_path, monkeypatch
    ) -> None:
        _silence_everything_except_citation_seed(monkeypatch)

        monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
        memory_store.reset_shared_store()
        get_memory_settings.cache_clear()
        try:
            store = memory_store.get_shared_store(
                db_path=str(tmp_path / "wiki_maintenance_contract.db")
            )
            result = _run(
                wiki_maintenance.run_wiki_maintenance(store, max_purges_per_axis=None)
            )
        finally:
            memory_store.reset_shared_store()
            get_memory_settings.cache_clear()

        assert result["status"] == "ok"
        assert "source_backfill" not in result
        assert "domain_backfill" not in result
        assert "citation_seed" not in result
        assert "lesson_promotion_backlog" not in result
        _no_stanza_errored(result)
