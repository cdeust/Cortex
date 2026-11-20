"""wiki_write records the page it wrote, not the page on disk when it records.

The ``wiki.pages`` row, its body hash included, is built from
``WriteResult.text`` (issue #715): the page this write left on disk. A
re-read after ``_store_pointer_memory`` could capture the page of another
writer and pair it with this write's ``memory_ids`` (Codex review of PR
#1092); an ``append`` passes only a fragment, which would make every appended
page read as ``failed``.

source: issue #715 (acceptance criterion 3); Codex P2 on PR #1092; notes of
the second review of PR #1092
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.handlers import wiki_write


@pytest.fixture
def recorded(tmp_path: Path, monkeypatch) -> list[tuple]:
    """The (rel_path, content, memory_ids, mode) each write handed to the recorder."""
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(tmp_path))
    calls: list[tuple] = []

    def record(*args):
        calls.append(args[:4])  # the fifth, the retraction frontier, is not text
        return (0, [])

    monkeypatch.setattr(wiki_write, "_retraction_frontier", lambda: 0)
    monkeypatch.setattr(wiki_write, "_sync_page_and_cite", record)
    return calls


def _write(content: str, mode: str = "create") -> dict:
    return asyncio.run(
        wiki_write.handler(
            {
                "path": "reference/a.md",
                "content": content,
                "mode": mode,
                "memory_ids": [10],
            }
        )
    )


def test_another_writer_between_write_and_record_is_not_recorded(
    recorded, tmp_path: Path, monkeypatch
):
    page = tmp_path / "reference" / "a.md"

    async def other_writer(rel_path, content, tags):
        page.write_text("# Other writer\n", encoding="utf-8")

    monkeypatch.setattr(wiki_write, "_store_pointer_memory", other_writer)
    result = _write("# A\n")
    assert recorded == [("reference/a.md", "# A\n", [10], "create")]
    assert result["citations_written"] == 0
    assert "citations_interrupted" not in result


def test_an_append_records_the_whole_page(recorded, monkeypatch):
    async def no_pointer(rel_path, content, tags):
        return None

    monkeypatch.setattr(wiki_write, "_store_pointer_memory", no_pointer)
    _write("# A")
    _write("more", mode="append")
    assert recorded[-1] == ("reference/a.md", "# A\n\nmore\n", [10], "append")
