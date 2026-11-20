"""Every wiki writer records the fingerprint ``wiki_read`` checks the page against.

``wiki_read`` reports ``failed`` when the recorded ``body_hash`` is not the
fingerprint of the page on disk (issue #715, criterion 3). ``wiki_write`` recorded
the hash of the parsed body; ``wiki_compile`` and ``ingest_findings`` the hash of
the markdown they passed to ``write_page``, before ``write_page`` normalised it.
A compiled page that a session read (``wiki_read`` then cites the page's memory)
read ``failed`` with nothing changed. Every writer now records
``page_text_hash`` of the page the write left on disk.

source: issue #715 (one fingerprint for every writer)
"""

from __future__ import annotations

import asyncio


from mcp_server.handlers.ingest_findings_artifacts import FindingRecord
from mcp_server.infrastructure.pg_store_wiki import page_text_hash
from tests_py.handlers.test_wiki_compile_sections_mirror import (
    _approved_draft,
    sqlite_store,  # noqa: F401 — the fixture the tests below request
)


def _recorded_and_on_disk(conn, page_id: int, wiki_root) -> tuple[str, str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT body_hash, rel_path FROM wiki.pages WHERE id = %s", (page_id,)
        )
        row = cur.fetchone()
    recorded, rel_path = (
        (row["body_hash"], row["rel_path"]) if isinstance(row, dict) else row
    )
    return recorded, rel_path, (wiki_root / rel_path).read_text(encoding="utf-8")


def _compile(conn, monkeypatch, wiki_root) -> int:
    from mcp_server.handlers.wiki_compile import handler as compile_drafts
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    monkeypatch.setattr("mcp_server.handlers.wiki_compile.WIKI_ROOT", wiki_root)
    draft_id = _approved_draft(conn)
    assert asyncio.run(compile_drafts({"draft_id": draft_id}))["errors"] == []
    return get_draft(conn, draft_id)["published_page_id"]


def test_a_compiled_page_records_the_fingerprint_of_the_page_on_disk(
    tmp_path,
    monkeypatch,
    sqlite_store,  # noqa: F811 — pytest fixture
):
    from mcp_server.handlers.wiki_migrate import page_row_from_md

    wiki = tmp_path / "wiki"
    page_id = _compile(sqlite_store._conn, monkeypatch, wiki)

    recorded, rel_path, text = _recorded_and_on_disk(sqlite_store._conn, page_id, wiki)
    assert text.startswith("---\n")
    assert recorded == page_text_hash(text)
    # a wiki_migrate sweep of the same page records the same fingerprint
    assert recorded == page_row_from_md(rel_path, text)["body_hash"]


def test_a_compiled_page_that_cites_a_memory_reads_current(
    tmp_path,
    monkeypatch,
    sqlite_store,  # noqa: F811 — pytest fixture
):
    from mcp_server.handlers import wiki_read
    from mcp_server.infrastructure.pg_store_wiki import insert_citation

    wiki = tmp_path / "wiki"
    page_id = _compile(sqlite_store._conn, monkeypatch, wiki)
    _, rel_path, _ = _recorded_and_on_disk(sqlite_store._conn, page_id, wiki)
    memory_id = sqlite_store.insert_memory(
        {"content": "the forces at play", "domain": "_general"}
    )
    # what wiki_read's session side effect records for a compiled page
    insert_citation(
        sqlite_store._conn,
        page_id=page_id,
        session_id="s1",
        domain="_general",
        memory_id=memory_id,
    )
    sqlite_store._conn.commit()
    monkeypatch.setattr(wiki_read, "WIKI_ROOT", str(wiki))

    page = asyncio.run(wiki_read.handler({"path": rel_path}))

    assert page["freshness"]["record_matches_text"] is True
    assert page["freshness"]["state"] == "current"


def test_a_finding_page_records_the_fingerprint_of_the_page_on_disk(
    tmp_path,
    monkeypatch,
    sqlite_store,  # noqa: F811 — pytest fixture
):
    from mcp_server.handlers import ingest_findings_writers as writers

    wiki = tmp_path / "wiki"
    monkeypatch.setattr(writers, "WIKI_ROOT", wiki)
    finding = FindingRecord(
        run_id="run1",
        finding_id="f1",
        verified=True,
        title="Symbol X leaks memory",
        description="Root cause: unbounded growth in cache Y.",
        refined_rel_path="findings/f1/stage-1.refined.json",
        file_paths=["src/foo.rs"],
        receipts=[],
        source_path=None,
    )

    page_id = writers.write_finding_page(sqlite_store._conn, finding, memory_id=None)

    recorded, _, text = _recorded_and_on_disk(sqlite_store._conn, page_id, wiki)
    assert text.startswith("---\n")
    assert recorded == page_text_hash(text)


def test_a_recompile_that_changes_only_the_tags_updates_the_row(
    tmp_path,
    monkeypatch,
    sqlite_store,  # noqa: F811 — pytest fixture
):
    from mcp_server.handlers.wiki_compile import handler as compile_drafts

    conn, wiki = sqlite_store._conn, tmp_path / "wiki"
    page_id = _compile(conn, monkeypatch, wiki)
    first, _, _ = _recorded_and_on_disk(conn, page_id, wiki)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE wiki.drafts SET frontmatter = %s, status = 'approved'",
            ('{"tags": ["retagged"]}',),
        )
        cur.execute("SELECT id FROM wiki.drafts")
        row = cur.fetchone()
    conn.commit()
    draft_id = row["id"] if isinstance(row, dict) else row[0]

    # the page exists: only a replace can publish it again
    assert asyncio.run(compile_drafts({"draft_id": draft_id}))["errors"] == []

    recorded, _, text = _recorded_and_on_disk(conn, page_id, wiki)
    assert "retagged" in text
    assert recorded == page_text_hash(text) != first
    with conn.cursor() as cur:
        cur.execute("SELECT tags FROM wiki.pages WHERE id = %s", (page_id,))
        tags = cur.fetchone()
    assert "retagged" in str(tags["tags"] if isinstance(tags, dict) else tags[0])
