"""Tests for ingest_codebase — fake the upstream MCP client + the memory store."""

from __future__ import annotations

import pytest

from mcp_server.handlers import ingest_codebase as icb
from mcp_server.handlers import ingest_helpers


class _FakeStore:
    def __init__(self):
        self.memories: list[dict] = []
        self.entities: list[dict] = []
        self.relationships: list[dict] = []
        self._next_mem = 1000
        self._next_ent = 2000

    def insert_memory(self, data: dict) -> int:
        mid = self._next_mem
        self._next_mem += 1
        data["id"] = mid
        self.memories.append(data)
        return mid

    def insert_entity(self, data: dict) -> int:
        eid = self._next_ent
        self._next_ent += 1
        data["id"] = eid
        self.entities.append(data)
        return eid

    def insert_relationship(self, data: dict) -> int:
        self.relationships.append(data)
        return len(self.relationships)

    def get_all_memories_for_decay(self) -> list[dict]:
        return list(self.memories)


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(icb, "_get_store", lambda: store)
    return store


@pytest.fixture
def fake_upstream(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    replies: dict[str, dict] = {}

    async def _call(server, tool, args):
        calls.append((server, tool, args))
        return replies.get(tool, {})

    monkeypatch.setattr(icb, "call_upstream", _call)
    return calls, replies


@pytest.fixture
def no_wiki(monkeypatch):
    written: list[tuple[str, str]] = []

    def _write(_root, rel, content, mode="replace"):
        written.append((rel, content))

    monkeypatch.setattr(icb, "write_page", _write)
    return written


class TestIngestCodebaseHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_writes_memories_entities_edges_and_pages(
        self, fake_store, fake_upstream, no_wiki
    ):
        calls, replies = fake_upstream
        replies["analyze_codebase"] = {"graph_path": "/tmp/graph", "node_count": 42}
        replies["search_codebase"] = {
            "results": [
                {
                    "qualified_name": "src/a.py::foo",
                    "kind": "function",
                    "calls": ["src/a.py::bar"],
                },
                {"qualified_name": "src/a.py::bar", "kind": "function", "calls": []},
            ]
        }
        replies["get_processes"] = {
            "processes": [
                {
                    "entry_point": "src/main.py::main",
                    "entry_kind": "main",
                    "bfs_depth": 2,
                    "symbol_count": 7,
                    "symbols": ["src/a.py::foo", "src/a.py::bar"],
                }
            ]
        }

        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )

        assert result["ingested"] is True
        assert result["graph_path"] == "/tmp/graph"
        assert result["memories_written"] == 2
        assert result["entities_written"] == 2
        assert result["edges_written"] == 1
        assert result["wiki_pages_written"] and result["wiki_pages_written"][
            0
        ].startswith("reference/codebase/")
        tools_called = {tool for (_, tool, _) in calls}
        assert {"analyze_codebase", "search_codebase", "get_processes"} <= tools_called

    @pytest.mark.asyncio
    async def test_reuses_cached_graph_when_memoised(
        self, fake_store, fake_upstream, no_wiki
    ):
        calls, replies = fake_upstream
        # Pre-load a memoised graph path for the project.
        ingest_helpers.memoise_graph_path(
            fake_store, "/tmp/myproj", "/tmp/existing-graph"
        )
        replies["search_codebase"] = {"results": []}
        replies["get_processes"] = {"processes": []}

        result = await icb.handler({"project_path": "/tmp/myproj"})

        assert result["ingested"] is True
        assert result["graph_path"] == "/tmp/existing-graph"
        assert result["analyze"]["reused_cached"] is True
        tools_called = [tool for (_, tool, _) in calls]
        assert "analyze_codebase" not in tools_called


class TestIngestCodebaseFailures:
    @pytest.mark.asyncio
    async def test_missing_project_path_rejects(self, fake_store):
        result = await icb.handler({})
        assert result["ingested"] is False
        assert "project_path" in result["reason"]

    @pytest.mark.asyncio
    async def test_analyze_failure_surfaces(self, fake_store, monkeypatch):
        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(icb, "call_upstream", _boom)
        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )
        assert result["ingested"] is False
        assert result["reason"] == "analyze_failed"
        assert "RuntimeError" in result["error"]
