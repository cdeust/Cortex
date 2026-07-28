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


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeStore:
    """Stand-in store; every sub-pass below is monkeypatched so this
    object's shape never actually matters to the passes it's threaded
    through."""


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
            "lesson_promotion_backlog": 0,
            "pending_total": 0,
        }

    monkeypatch.setattr(wiki_maintenance, "run_backlog_pass", _noop_backlog)


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
