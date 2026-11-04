"""End to end: repeated text in different sections is recalled as distinct,
versioned segments (issue #713, slice 1)."""

from __future__ import annotations

import pytest

from mcp_server.handlers import ingest_document


class _Store:
    def __init__(self):
        self.memories: list[dict] = []

    def insert_memory(self, data: dict) -> int:
        self.memories.append({**data, "id": 1000 + len(self.memories)})
        return self.memories[-1]["id"]

    def get_memories_by_tag(self, tag, limit=20, heads_only=True, source=None):
        return [
            m
            for m in self.memories
            if tag in m["tags"] and source in (None, m.get("source"))
        ]


async def _no_wiki(root, rel_path, content, *, mode="create", **_kw):
    return {"path": rel_path, "created": True, "bytes_written": len(content)}


@pytest.mark.asyncio
async def test_repeated_section_text_lands_in_distinct_versioned_memories(
    monkeypatch, tmp_path
):
    store = _Store()
    monkeypatch.setattr(ingest_document, "WIKI_ROOT", tmp_path / "wiki")
    monkeypatch.setattr(ingest_document, "_get_store", lambda: store)
    monkeypatch.setattr(ingest_document, "write_governed_page", _no_wiki)
    page = tmp_path / "guide.xml"
    page.write_text(
        "<h1>Install</h1><p>steps a</p><h2>Notes</h2><p>restart required</p>"
        "<h1>Uninstall</h1><p>steps b</p><h2>Notes</h2><p>restart required</p>",
        encoding="utf-8",
    )
    out = await ingest_document.handler({"path": str(page)})
    assert out["ingested"] is True
    by_id = {m["id"]: m for m in store.memories}
    sections = [by_id[i]["content"] for i in out["section_memory_ids"]]
    assert sections == [
        "[Install]\n\nsteps a",
        "[Install > Notes]\n\nrestart required",
        "[Uninstall]\n\nsteps b",
        "[Uninstall > Notes]\n\nrestart required",
    ]
    version_tag = f"doc-ingest:confluence-export:{page}@{out['version']}"
    assert all(version_tag in by_id[i]["tags"] for i in out["section_memory_ids"])
