"""What wiki_write hands its citation step: store, page row, domain, findings.

Pins the inputs ``_sync_page_and_cite`` and ``_cite_memories`` pass on, with
the fidelity fakes of ``test_wiki_write_citations.py``: the store is opened
with the configured path and dimension, a citation needs a real page row
(id 0 included), each citation carries the page domain, and the prose
findings stay in the response beside the citation count.

source: issue #715 (slice 1), mutation gate of PR #1081
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mcp_server.handlers import wiki_write
from tests_py.handlers import test_wiki_write_citations as base

_FakeConn = base._FakeConn
_FakeStore = base._FakeStore
_run = base._run
# the fixtures of the base module, under the names the tests below request
tmp_wiki = base.tmp_wiki
wired_pg = base.wired_pg


def test_the_store_is_opened_with_the_configured_path_and_dimension(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    settings = SimpleNamespace(DB_PATH="/data/cortex.db", EMBEDDING_DIM=384)
    pages, _ = wired_pg
    opened: list[tuple] = []
    store = _FakeStore(_FakeConn(), pages.request_conn, pages.violations)
    monkeypatch.setattr(wiki_write, "get_memory_settings", lambda: settings)

    def _open(*args, **kwargs):
        opened.append((args, kwargs))
        return store

    monkeypatch.setattr(wiki_write, "get_shared_store", _open)
    _run(wiki_write.handler({"path": "reference/a.md", "content": "# A"}))
    # once to read the retraction frontier, once for the citation unit
    assert opened == [(("/data/cortex.db", 384), {})] * 2


@pytest.mark.parametrize(("page_id", "expected"), [(0, 1), (-1, 0), (None, 0)])
def test_citations_need_a_real_page_row(
    tmp_wiki, wired_pg, monkeypatch, page_id, expected
) -> None:
    _, citations = wired_pg
    monkeypatch.setattr(wiki_write, "upsert_page", lambda conn, row: (page_id, True))
    result = _run(
        wiki_write.handler(
            {"path": "reference/a.md", "content": "# A", "memory_ids": [10]}
        )
    )
    assert result["citations_written"] == expected
    # an unresolved page row records no citation; nothing was interrupted
    assert "citations_interrupted" not in result
    assert [r[0] for r in citations.rows] == [page_id] * expected


@pytest.mark.parametrize(
    ("row_extra", "domain"), [({"domain": "eng"}, "eng"), ({}, "")]
)
def test_each_citation_carries_the_page_domain(
    tmp_wiki, wired_pg, monkeypatch, row_extra, domain
) -> None:
    _, citations = wired_pg
    monkeypatch.setattr(
        wiki_write,
        "page_row_from_md",
        lambda rel_path, content: {"rel_path": rel_path, **row_extra},
    )
    _run(
        wiki_write.handler(
            {"path": "reference/a.md", "content": "# A", "memory_ids": [10, 20]}
        )
    )
    assert [r[2] for r in citations.rows] == [domain, domain]


def test_prose_findings_are_reported_beside_the_citations(tmp_wiki, wired_pg) -> None:
    result = _run(
        wiki_write.handler(
            {
                "path": "reference/a.md",
                "content": "# A\n\nThe store is fast — very fast.\n",
                "memory_ids": [10],
            }
        )
    )
    assert result["citations_written"] == 1
    assert result["redaction_findings"]["count"] == 1
    assert result["redaction_findings"]["first"][0]["line"] == 3
