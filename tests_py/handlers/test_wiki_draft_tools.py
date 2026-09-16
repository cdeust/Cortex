"""The Path B draft tools are reachable over MCP (issue #579).

`wiki_get_draft` and `wiki_refine_draft` existed as handlers since ADR-0467
with no registration, so no client could call them and `wiki_get_draft`'s own
instructions named a tool that did not exist. These tests hold the two tools
on the registered surface: their names and annotations, the arguments a
client sends reaching the handler, and one call landing in the store.

source: ADR-1066
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server import tool_registry_wiki_drafts as registry
from mcp_server.handlers import wiki_refine

REFINED_LEAD = "pgvector was chosen because HNSW gives sublinear ANN search."


def _server() -> MCPServer:
    mcp = MCPServer(name="wiki-draft-tools-test")
    registry.register(mcp)
    return mcp


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


async def _pending_draft_id(store) -> int:
    from mcp_server.handlers.wiki_extract import handler as extract
    from mcp_server.handlers.wiki_synthesize import handler as synthesize
    from mcp_server.infrastructure.pg_store_wiki import list_drafts

    store.insert_memory(
        {
            "content": "We decided to use pgvector because HNSW gives "
            "sublinear ANN search.",
            "domain": "eng",
            "memory_type": "decision",
        }
    )
    await extract({"limit": 50})
    await synthesize({"limit": 50})
    drafts = list_drafts(store._conn, status="pending", limit=1)
    assert drafts, "the synthesizer produced no pending draft"
    return int(drafts[0]["id"])


def test_both_path_b_tools_are_registered() -> None:
    tools = asyncio.run(_server().list_tools())
    by_name = {t.name: t for t in tools}

    assert set(by_name) == {"wiki_get_draft", "wiki_refine_draft"}
    assert by_name["wiki_get_draft"].annotations.read_only_hint is True
    assert by_name["wiki_refine_draft"].annotations.read_only_hint is False
    assert by_name["wiki_refine_draft"].annotations.idempotent_hint is False


def test_get_draft_tool_forwards_its_listing_arguments() -> None:
    spy = AsyncMock(return_value={"drafts": [], "count": 0})
    with patch.object(wiki_refine, "handler_get", spy):
        asyncio.run(
            _server().call_tool(
                "wiki_get_draft",
                {"list_pending": True, "kind": "adr", "limit": 5},
            )
        )

    args = spy.call_args.args[0]
    assert args["list_pending"] is True
    assert args["kind"] == "adr"
    assert args["limit"] == 5
    assert args["draft_id"] is None


def test_refine_tool_forwards_its_content_arguments() -> None:
    sections = [{"heading": "Context", "body": "prose", "claim_ids": [1]}]
    spy = AsyncMock(return_value={"draft_id": 7, "updated": True})
    with patch.object(wiki_refine, "handler_refine", spy):
        asyncio.run(
            _server().call_tool(
                "wiki_refine_draft",
                {
                    "draft_id": 7,
                    "lead": REFINED_LEAD,
                    "sections": sections,
                    "rationale": "grounded the lead in the claims",
                },
            )
        )

    args = spy.call_args.args[0]
    assert args["draft_id"] == 7
    assert args["lead"] == REFINED_LEAD
    assert args["sections"] == sections
    assert args["rationale"] == "grounded the lead in the claims"
    assert args["synth_model"] == "claude_refine_v1"


@pytest.mark.asyncio
async def test_refine_tool_call_reaches_the_store(sqlite_store) -> None:
    from mcp_server.infrastructure.pg_store_wiki import get_draft

    draft_id = await _pending_draft_id(sqlite_store)

    await _server().call_tool(
        "wiki_refine_draft",
        {"draft_id": draft_id, "lead": REFINED_LEAD},
    )

    assert get_draft(sqlite_store._conn, draft_id)["lead"] == REFINED_LEAD
