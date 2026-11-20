"""A rewrite that changes only the frontmatter updates the page's row.

Every writer records ``page_text_hash`` of the whole page, frontmatter included
(issue #715, PR #1095), so ``upsert_page``'s no-op guard no longer skips a
rewrite that changes only the tags. The ``wiki_compile`` case is covered in
``test_wiki_writers_record_the_hash_wiki_read_checks.py``; these tests cover
``wiki_write`` and a ``wiki_migrate`` sweep, the two writers that recorded the
hash of the body alone before PR #1095.

source: issue #715; notes of reviews 1 and 2 of PR #1095
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp_server.handlers import wiki_write
from mcp_server.handlers.wiki_migrate import migrate_wiki
from mcp_server.infrastructure.pg_store_wiki import page_text_hash
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from tests_py.handlers.test_wiki_read_sources import _page_md

_PAGE = "notes/key-rotation.md"


def _retagged(text: str) -> str:
    return text.replace(
        "provenance: human\n", "provenance: human\ntags:\n  - retagged\n"
    )


def _conn():
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)._conn


def _row(conn) -> tuple[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT body_hash, tags FROM wiki.pages WHERE rel_path = %s", (_PAGE,)
        )
        row = cur.fetchone()
    if isinstance(row, dict):
        return row["body_hash"], str(row["tags"])
    return row[0], str(row[1])


def _write(wiki: Path, content: str, mode: str) -> None:
    out = asyncio.run(
        wiki_write.handler({"path": _PAGE, "content": content, "mode": mode})
    )
    assert out.get("error") is None, out


def test_wiki_write_records_a_rewrite_that_changes_only_the_tags(monkeypatch, tmp_path):
    wiki = tmp_path / "wiki"
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(wiki))
    conn = _conn()
    _write(wiki, _page_md("Key rotation"), "create")
    first, _ = _row(conn)

    _write(wiki, _retagged(_page_md("Key rotation")), "replace")

    recorded, tags = _row(conn)
    text = (wiki / _PAGE).read_text(encoding="utf-8")
    assert "retagged" in text
    assert recorded == page_text_hash(text) != first
    assert "retagged" in tags


def test_a_wiki_migrate_sweep_records_a_page_retagged_on_disk(monkeypatch, tmp_path):
    wiki = tmp_path / "wiki"
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(wiki))
    conn = _conn()
    _write(wiki, _page_md("Key rotation"), "create")
    first, _ = _row(conn)
    page = wiki / _PAGE
    page.write_text(_retagged(page.read_text(encoding="utf-8")), encoding="utf-8")

    summary = migrate_wiki(wiki, conn, dry_run=False)

    assert summary["error_count"] == 0, summary["errors"]
    recorded, tags = _row(conn)
    assert recorded == page_text_hash(page.read_text(encoding="utf-8")) != first
    assert "retagged" in tags
