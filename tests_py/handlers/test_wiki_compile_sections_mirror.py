"""The wiki.pages mirror holds what the page holds (issue #589).

`handlers/wiki_compile.py` built the mirror as {heading: body} with no guard,
so a section with no usable heading landed in `wiki.pages.sections` under an
empty key while the rendered Markdown dropped it, the two disagreeing about
the same page.

source: ADR-1071
"""

from __future__ import annotations

import json

import pytest

SECTIONS = [
    {"heading": "Context", "body": "The forces at play."},
    {"heading": "   ", "body": "orphan prose with no heading"},
    {"body": "no heading key at all"},
    {"heading": 3, "body": "a heading that is not text"},
]


@pytest.fixture()
def sqlite_store(tmp_path, monkeypatch):
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure.memory_store import (
        get_shared_store,
        reset_shared_store,
    )

    db = tmp_path / "memory.db"
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setenv("CORTEX_MEMORY_DB_PATH", str(db))
    monkeypatch.setenv("CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(db))
    get_memory_settings.cache_clear()
    reset_shared_store()

    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    yield store

    reset_shared_store()
    get_memory_settings.cache_clear()


def _approved_draft(conn) -> int:
    from mcp_server.infrastructure.pg_store_wiki import (
        insert_draft,
        update_draft_status,
    )

    draft_id = insert_draft(
        conn,
        {
            "memory_id": None,
            "concept_id": None,
            "title": "Section mirror",
            "kind": "note",
            "lead": "A page whose draft carries a headless section.",
            "sections": SECTIONS,
            "frontmatter": {"tags": []},
            "confidence": 0.8,
            "status": "pending",
            "synth_model": "template_v1",
        },
    )
    update_draft_status(conn, draft_id, status="approved")
    conn.commit()
    return draft_id


@pytest.mark.asyncio
async def test_the_mirror_holds_only_the_sections_the_page_carries(
    tmp_path, monkeypatch, sqlite_store
):
    from mcp_server.handlers.wiki_compile import handler as compile_drafts
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    # The handler binds WIKI_ROOT at import time (a value copy), so the
    # redirection has to land on its own module attribute.
    monkeypatch.setattr("mcp_server.handlers.wiki_compile.WIKI_ROOT", tmp_path / "wiki")
    draft_id = _approved_draft(sqlite_store._conn)

    out = await compile_drafts({"draft_id": draft_id})

    assert out["errors"] == []
    page_id = get_draft(sqlite_store._conn, draft_id)["published_page_id"]
    with sqlite_store._conn.cursor() as cur:
        cur.execute(
            "SELECT sections, rel_path FROM wiki.pages WHERE id = %s", (page_id,)
        )
        row = cur.fetchone()
    sections = row["sections"] if isinstance(row, dict) else row[0]
    rel_path = row["rel_path"] if isinstance(row, dict) else row[1]
    if isinstance(sections, str):
        sections = json.loads(sections)
    published = (tmp_path / "wiki" / rel_path).read_text(encoding="utf-8")

    assert sections == {"Context": "The forces at play."}
    assert "orphan prose" not in published
    assert "## Context" in published
