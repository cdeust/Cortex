"""A memory-derived page across waves of addition, correction and deletion.

Issue #715, criterion 1, end to end on the real store: each wave changes the
memories the page was written from, ``wiki_read`` says the page is no longer
current, and the full rewrite the host makes from the memories that remain
brings it back to ``current``, citing the still-valid memories only: the
corrected one at its new head, the erased one gone.

The memories are those of the codebase docs pass (``write_doc_memory``): a
changed document supersedes its memory (``supersede_atomic``), which is the
correction this test needs. ``ingest_document`` keeps every version of a
document live, so a new version is an addition there, not a correction.

source: issue #715 (criterion 1, end-to-end slice)
"""

from __future__ import annotations

import asyncio

from mcp_server.core.wiki_page_freshness import PAGE_CURRENT, PAGE_PENDING
from mcp_server.handlers import forget, wiki_read, wiki_write
from mcp_server.handlers.ingest_docs_content_writers import write_doc_memory
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from tests_py.handlers.test_wiki_read_sources import _page_md

_PAGE = "notes/key-rotation.md"
_DOMAIN = "code:waves"


def _doc(rel_path: str, text: str) -> tuple[int, bool]:
    """Write one document's memory; return its id and whether it superseded."""
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    memory_id, written, superseded = write_doc_memory(
        store, _DOMAIN, "/repo", rel_path, text
    )
    assert written
    return memory_id, superseded


def _write(mode: str, title: str, memory_ids: list[int]) -> None:
    args = {"path": _PAGE, "content": _page_md(title), "mode": mode}
    out = asyncio.run(wiki_write.handler({**args, "memory_ids": memory_ids}))
    assert "citations_interrupted" not in out
    assert out["citations_written"] == len(memory_ids)


def _read() -> dict:
    page = asyncio.run(wiki_read.handler({"path": _PAGE}))
    assert "sources_unavailable" not in page
    return page


def _cited(page: dict) -> list[int]:
    return [ref["memory_id"] for ref in page["sources"]]


def _first_wave(monkeypatch, tmp_path) -> list[int]:
    """Wave 1, addition: the page is written from two documents."""
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(tmp_path / "wiki"))
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(tmp_path / "wiki"))
    cited = [
        _doc("docs/keys.md", "Rotate the zelkova keys every week.")[0],
        _doc("docs/cache.md", "Flush the vantor cache after a rotation.")[0],
    ]
    _write("create", "Key rotation", cited)
    assert _read()["freshness"]["state"] == PAGE_CURRENT
    return cited


def _erase_then_append(monkeypatch, cache: int) -> None:
    """Wave 3, deletion: a hard forget erases the cache document's memory.

    An append then adds to the page; it is not the refresh the erasure waits for.
    """
    monkeypatch.setattr(forget, "_store", None)
    erased = asyncio.run(forget.handler({"memory_id": cache}))
    assert erased["method"] == "hard" and erased["cited_by_pages"] == [_PAGE]
    freshness = _read()["freshness"]
    assert freshness["state"] == PAGE_PENDING
    assert freshness["retracted_sources"] == 1
    out = asyncio.run(
        wiki_write.handler({"path": _PAGE, "content": "More.\n", "mode": "append"})
    )
    assert "error" not in out  # review of PR #1114, note 2
    assert _read()["freshness"]["state"] == PAGE_PENDING


def test_each_wave_is_pending_until_the_rewrite_drops_what_it_retracted(
    monkeypatch, tmp_path
):
    keys, cache = _first_wave(monkeypatch, tmp_path)

    # Wave 2, addition and correction: the corrected document supersedes.
    queue, _ = _doc("docs/queue.md", "Drain the quorin queue before a rotation.")
    corrected, superseded = _doc("docs/keys.md", "Rotate the zelkova keys daily.")
    assert superseded and corrected != keys
    page = _read()
    assert page["freshness"]["state"] == PAGE_PENDING
    assert page["freshness"]["pending_memory_ids"] == [keys]
    assert page["sources"][0]["superseded_by_id"] == corrected

    _write("replace", "Key rotation, corrected", [corrected, cache, queue])
    page = _read()
    assert page["freshness"]["state"] == PAGE_CURRENT
    assert _cited(page) == [cache, corrected, queue]  # cache's row is kept

    _erase_then_append(monkeypatch, cache)
    _write("replace", "Key rotation, without the erased source", [corrected, queue])
    page = _read()
    assert page["content"].endswith(
        "# Key rotation, without the erased source\n\nSynthesis.\n"
    )
    assert _cited(page) == [corrected, queue]
    assert page["freshness"] == {
        "state": PAGE_CURRENT,
        "record_matches_text": True,
        "retracted_sources": 0,
        "pending_memory_ids": [],
        "frontier": {"cited_memories": 2, "max_memory_id": max(corrected, queue)},
    }
