"""I6-D7/INC6.8: curate_wiki's reverse loop (``report_uncited_deliberate``).

Read-only report — never writes a page, a job, or a citation.
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers import curate_wiki, curate_wiki_uncited
from tests_py._store_call import FakeConnStore, mark_test_operation


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeStore(FakeConnStore):
    """PostgreSQL-shaped store; the listing operation is monkeypatched."""


def test_report_mode_returns_candidates_without_generating_jobs(monkeypatch) -> None:
    rows = [{"id": 7, "content_preview": "deliberate fact", "importance": 0.9}]
    monkeypatch.setattr(curate_wiki_uncited, "get_shared_store", lambda: _FakeStore())
    monkeypatch.setattr(
        curate_wiki_uncited,
        "list_uncited_deliberate_memories",
        mark_test_operation(lambda conn, limit: rows),
    )

    result = _run(
        curate_wiki.handler(
            {"report_uncited_deliberate": True, "uncited_deliberate_limit": 5}
        )
    )

    assert result["mode"] == "report_uncited_deliberate"
    assert result["candidates"] == rows
    assert result["candidate_count"] == 1
    assert "jobs" not in result


def test_report_mode_degrades_to_empty_on_db_failure(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("PG unreachable")

    monkeypatch.setattr(curate_wiki_uncited, "get_shared_store", _boom)

    result = _run(curate_wiki.handler({"report_uncited_deliberate": True}))

    assert result["candidates"] == []
    assert result["candidate_count"] == 0


def test_default_call_still_returns_jobs_not_report(monkeypatch) -> None:
    """report_uncited_deliberate defaults False — normal job flow unaffected."""

    class _EmptyStore:
        def get_recently_accessed_memories(self, **kw):
            return []

        def get_recent_memories(self, **kw):
            return []

    monkeypatch.setattr(curate_wiki, "get_shared_store", lambda: _EmptyStore())

    result = _run(curate_wiki.handler({}))

    assert "mode" not in result
    assert "jobs" in result
