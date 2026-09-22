"""Contract test (#636): every batch_pool-gated consolidation pass must
degrade to a named ``skipped: ...`` status against a real, fresh
SqliteMemoryStore built through the actual composition root -- never an
``error: ...`` status born of an unguarded ``AttributeError`` on
``store.batch_pool``.

Covers the four passes named in #636 (the three wired into
``consolidate`` plus the backlog's lesson-promotion count) and, since the
same defect shape and the same guard now apply there too, the five
standalone-campaign passes flagged by the same issue as unverified
suspects.

source: ADR-1089
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SqliteMemoryStore(path)
    yield s
    try:
        os.remove(path)
    except OSError:
        pass


def _assert_skipped_not_errored(result: dict) -> None:
    status = result["status"]
    assert not status.startswith("error:"), f"unexpected error status: {status}"
    assert status.startswith("skipped:"), f"expected a named skip, got: {status}"


class TestWikiPassesSkipCleanlyOnSqlite:
    """The three passes #636 reported as silently broken."""

    def test_source_backfill_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.wiki_source_backfill_pass import (
            run_source_backfill_pass,
        )

        _assert_skipped_not_errored(_run(run_source_backfill_pass(store)))

    def test_domain_backfill_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.wiki_domain_backfill_pass import (
            run_domain_backfill_pass,
        )

        _assert_skipped_not_errored(_run(run_domain_backfill_pass(store)))

    def test_citation_seed_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.wiki_citation_seed_pass import (
            run_wiki_citation_seed_pass,
        )

        _assert_skipped_not_errored(_run(run_wiki_citation_seed_pass(store)))

    def test_lesson_promotion_backlog_degrades_to_none_silently(self, store) -> None:
        from mcp_server.handlers.consolidation import wiki_backlog_pass
        from mcp_server.observability import silent_failure

        silent_failure.reset()
        result = wiki_backlog_pass._lesson_promotion_backlog(store)
        assert result is None
        # The missing capability is expected on SQLite -- it must not be
        # recorded as a silent failure (that would fire, and increment
        # cortex_silent_failures_total, on every consolidate run for the
        # lifetime of a SQLite install).
        assert (
            "wiki_backlog_pass.lesson_promotion_backlog" not in silent_failure.status()
        )


class TestStandaloneCampaignPassesSkipCleanlyOnSqlite:
    """Same unconditional store.batch_pool defect, same guard, applied to
    the five standalone-campaign passes #636 flagged as unverified."""

    def test_memory_dedup_exact_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.memory_dedup_exact_pass import (
            run_memory_dedup_exact_pass,
        )

        _assert_skipped_not_errored(_run(run_memory_dedup_exact_pass(store)))

    def test_memory_domain_backfill_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.memory_domain_backfill_pass import (
            run_memory_domain_backfill_pass,
        )

        _assert_skipped_not_errored(_run(run_memory_domain_backfill_pass(store)))

    def test_memory_reheat_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.memory_reheat_pass import (
            run_memory_reheat_pass,
        )

        _assert_skipped_not_errored(_run(run_memory_reheat_pass(store)))

    def test_near_dup_sample_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.near_dup_calibration_pass import (
            run_near_dup_sample,
        )

        _assert_skipped_not_errored(_run(run_near_dup_sample(store)))

    def test_near_dup_apply_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.near_dup_calibration_pass import (
            run_near_dup_apply_pass,
        )

        _assert_skipped_not_errored(_run(run_near_dup_apply_pass(store, threshold=0.9)))

    def test_write_class_backfill_pass(self, store) -> None:
        from mcp_server.handlers.consolidation.write_class_backfill_pass import (
            run_write_class_backfill_pass,
        )

        _assert_skipped_not_errored(_run(run_write_class_backfill_pass(store)))
