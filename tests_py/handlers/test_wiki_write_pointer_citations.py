"""A wiki page cannot rest on itself, or on a page that cites it back.

``wiki_write`` registers a pointer memory (source ``wiki://<rel_path>``) for
every page it writes. Cited by a page, that pointer would make a derived page
its own source, directly or through another page: a citation cycle. The write
refuses it, names it in ``citations_refused``, and the page's trace keeps
only the memories it was really authored from.

source: issue #715 (slice 1, acceptance criterion 4)
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers import wiki_read, wiki_write
from mcp_server.shared.wiki_pointer import pointer_source
from tests_py.handlers.test_wiki_read_sources import (
    _page_md,
    _two_documents_and_a_page,
)

_PAGE = "notes/key-rotation.md"


def _pointer_id(rel_path: str) -> int:
    settings = wiki_write.get_memory_settings()
    store = wiki_write.get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    with store._conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM memories WHERE source = %s", (pointer_source(rel_path),)
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    row = rows[0]
    return int(row["id"] if isinstance(row, dict) else row[0])


def _write(rel_path: str, memory_ids: list[int], mode: str = "create") -> dict:
    out = asyncio.run(
        wiki_write.handler(
            {
                "path": rel_path,
                "content": _page_md("Derived"),
                "mode": mode,
                "memory_ids": memory_ids,
            }
        )
    )
    assert "error" not in out
    return out


def _traced(rel_path: str) -> list[int]:
    page = asyncio.run(wiki_read.handler({"path": rel_path}))
    assert "sources_unavailable" not in page
    return [ref["memory_id"] for ref in page["sources"]]


def test_a_page_citing_another_pages_pointer_is_refused_that_citation(
    monkeypatch, tmp_path
):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    pointer = _pointer_id(_PAGE)
    out = _write("notes/derived.md", [pointer, cited[0]])
    assert out["citations_written"] == 1
    assert out["citations_refused"] == [
        {"memory_id": pointer, "reason": "wiki_pointer"}
    ]
    assert _traced("notes/derived.md") == [cited[0]]


def test_a_page_cannot_cite_its_own_pointer(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    pointer = _pointer_id(_PAGE)
    out = _write(_PAGE, [pointer], mode="replace")
    assert out["citations_written"] == 0
    assert out["citations_refused"] == [
        {"memory_id": pointer, "reason": "wiki_pointer"}
    ]
    assert _traced(_PAGE) == cited


def test_a_write_citing_no_pointer_carries_no_refusal(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    out = _write("notes/derived.md", cited)
    assert out["citations_written"] == 2
    assert "citations_refused" not in out
