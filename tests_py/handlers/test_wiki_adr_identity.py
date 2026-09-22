"""Canonical ADR publication contract, issue #514 / ADR-0056."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from mcp_server.handlers import remember, wiki_adr
from mcp_server.infrastructure.wiki_decision_index import decision_index
from mcp_server.shared.wiki_pointer import POINTER_CONTENT_MAX_CHARS


def test_pointer_starts_with_citable_identity(monkeypatch):
    captured = []

    async def capture(args):
        captured.append(args)

    monkeypatch.setattr(remember, "handler", capture)
    asyncio.run(wiki_adr._store_pointer_memory("adr/0056-test.md", "---\n" * 200, []))
    assert captured[0]["content"].startswith("ADR-0056\n")
    # The budget is a cap, not a target: the cut lands on the last word
    # boundary that fits, so the length is at most the budget (issue #622).
    assert len(captured[0]["content"]) <= POINTER_CONTENT_MAX_CHARS


def test_concurrent_authors_allocate_unique_canonical_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(wiki_adr, "WIKI_ROOT", tmp_path)

    async def noop(*args):
        pass

    monkeypatch.setattr(wiki_adr, "_store_pointer_memory", noop)

    def publish(title):
        return asyncio.run(
            wiki_adr.handler(
                {
                    "title": title,
                    "context": "Prior evidence",
                    "decision": "Keep an explicit identity",
                    "consequences": "Exact citations",
                }
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(publish, ["first decision", "second decision"]))
    assert sorted(result["number"] for result in results) == [56, 57]
    assert set(decision_index(tmp_path)) == {"ADR-0056", "ADR-0057"}
