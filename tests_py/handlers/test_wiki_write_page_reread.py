"""wiki_write records nothing, and says so, when the written page cannot be re-read.

The ``wiki.pages`` row is built from the page re-read after the write
(``_record_page``, issue #715), so ``wiki_read`` can compare its body hash
with the page. When that re-read finds no page or fails, nothing is recorded,
the response carries ``citations_interrupted`` and the failure is noted.

source: issue #715 (acceptance criterion 3); mutants 7 to 13 of
``_record_page`` that survived on PR #1092 (job 134047721391)
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.handlers import wiki_write
from mcp_server.observability import silent_failure


@pytest.fixture(autouse=True)
def _clean_silent_failure():
    """The failure registry is process-wide: leave it as each test found it."""
    silent_failure.reset()
    yield
    silent_failure.reset()


@pytest.fixture
def never_synced(tmp_path: Path, monkeypatch) -> list[tuple]:
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(tmp_path))
    calls: list[tuple] = []
    monkeypatch.setattr(wiki_write, "_sync_page_and_cite", lambda *a: calls.append(a))
    return calls


def _write() -> dict:
    return asyncio.run(
        wiki_write.handler(
            {"path": "reference/a.md", "content": "# A", "memory_ids": [10]}
        )
    )


def _assert_nothing_recorded(result: dict, calls: list, last_error: str) -> None:
    assert "error" not in result
    assert result["citations_written"] == 0
    assert result["citations_interrupted"] is True
    assert calls == []
    noted = silent_failure.status()["wiki_write.page_reread"]
    assert noted == {"last_error": last_error, "count": 1}


def test_a_page_gone_before_its_re_read_records_nothing(never_synced, monkeypatch):
    monkeypatch.setattr(wiki_write, "read_page", lambda root, rel: None)
    _assert_nothing_recorded(_write(), never_synced, "WikiMissingError: reference/a.md")


def test_a_failed_re_read_records_nothing(never_synced, monkeypatch):
    def unreadable(root, rel):
        raise PermissionError("denied")

    monkeypatch.setattr(wiki_write, "read_page", unreadable)
    _assert_nothing_recorded(_write(), never_synced, "PermissionError: denied")
