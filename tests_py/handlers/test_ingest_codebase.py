"""Tests for ingest_codebase — fake the upstream MCP client + the memory store."""

from __future__ import annotations

import re

import pytest

from mcp_server.handlers import ingest_codebase as icb
from mcp_server.handlers import ingest_codebase_pages as icb_pages
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


# Cypher pattern → reply for the fake upstream. Tests register a list
# of (compiled_regex, payload) tuples; the first regex that fully
# matches the cypher query wins. Regex routing avoids the substring-
# ordering footgun in earlier mock generations.
def _route_cypher(routes: list[tuple[re.Pattern[str], dict]], cypher: str) -> dict:
    for pattern, payload in routes:
        if pattern.search(cypher):
            return payload
    return {"rows": [], "columns": []}


@pytest.fixture
def fake_upstream(monkeypatch):
    calls: list[tuple[str, str, dict]] = []
    replies: dict[str, dict | list] = {}

    async def _call(server, tool, args):
        calls.append((server, tool, args))
        if tool == "query_graph":
            routes = replies.get("query_graph") or []
            cypher = (args or {}).get("query", "")
            return _route_cypher(routes, cypher)
        return replies.get(tool, {})

    monkeypatch.setattr(icb, "call_upstream", _call)
    monkeypatch.setattr(
        "mcp_server.handlers.ingest_codebase_cypher.call_upstream", _call
    )
    monkeypatch.setattr(
        "mcp_server.handlers.ingest_codebase_graph.call_upstream", _call
    )
    return calls, replies


@pytest.fixture
def no_wiki(monkeypatch):
    written: list[tuple[str, str]] = []

    def _write(_root, rel, content, mode="replace"):
        written.append((rel, content))

    monkeypatch.setattr(icb_pages, "write_page", _write)
    return written


def _re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


class TestIngestCodebaseHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_writes_memories_entities_edges_and_pages(
        self, fake_store, fake_upstream, no_wiki
    ):
        calls, replies = fake_upstream
        replies["analyze_codebase"] = {"graph_path": "/tmp/graph", "node_count": 42}
        replies["query_graph"] = [
            (
                _re(r"MATCH \(n:Function\)(?!-)"),
                {
                    "columns": [
                        "qualified_name",
                        "name",
                        "start_line",
                        "end_line",
                        "visibility",
                    ],
                    "rows": [
                        ["src/a.py::foo", "foo", 1, 10, ""],
                        ["src/a.py::bar", "bar", 15, 20, ""],
                    ],
                },
            ),
            (_re(r"MATCH \(n:Method\)(?!-)"), {"columns": [], "rows": []}),
            (_re(r"MATCH \(n:Struct\)(?!-)"), {"columns": [], "rows": []}),
            (
                _re(r"MATCH \(f:File\)-\[\]->\(n:Function\|Method\|Struct\)"),
                {
                    "columns": ["file_path", "qn"],
                    "rows": [
                        ["src/a.py", "src/a.py::foo"],
                        ["src/a.py", "src/a.py::bar"],
                    ],
                },
            ),
            (
                _re(r"MATCH \(f:File\)(?!-)"),
                {
                    "columns": ["path", "name", "extension", "size_bytes"],
                    "rows": [["src/a.py", "a.py", "py", 100]],
                },
            ),
            (
                _re(r"MATCH \(a:Function\)-\[\]->\(b:Function\|Method\|Struct\)"),
                {
                    "columns": ["src", "dst"],
                    "rows": [["src/a.py::foo", "src/a.py::bar"]],
                },
            ),
            (
                _re(r"MATCH \(a:Method\)-\[\]->\(b:Function\|Method\|Struct\)"),
                {"columns": [], "rows": []},
            ),
            (
                _re(r"MATCH \(a:Struct\)-\[\]->\(b:Function\|Method\|Struct\)"),
                {"columns": [], "rows": []},
            ),
        ]
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
        assert result["memories_written"] == 3
        assert result["entities_written"] == 3
        assert result["edges_written"] == 3
        assert result["wiki_pages_written"] and result["wiki_pages_written"][
            0
        ].startswith("reference/codebase/")
        tools_called = {tool for (_, tool, _) in calls}
        assert {"analyze_codebase", "query_graph", "get_processes"} <= tools_called
        assert "diagnostics" not in result

    @pytest.mark.asyncio
    async def test_reuses_cached_graph_when_memoised(
        self, fake_store, fake_upstream, no_wiki
    ):
        calls, replies = fake_upstream
        ingest_helpers.memoise_graph_path(
            fake_store, "/tmp/myproj", "/tmp/existing-graph"
        )
        replies["query_graph"] = []
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
        monkeypatch.setattr(
            "mcp_server.handlers.ingest_codebase_graph.call_upstream", _boom
        )
        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )
        assert result["ingested"] is False
        assert result["reason"] == "analyze_failed"
        assert "RuntimeError" in result["error"]

    @pytest.mark.asyncio
    async def test_persistent_upstream_error_does_not_poison_cache(
        self, fake_store, fake_upstream
    ):
        """ensure_graph must NOT memoise a synthesized path when upstream
        returns status=error. Otherwise the next ingest reuses the bogus
        path and silently projects an empty graph (Liskov/Dijkstra
        audits Apr-2026)."""
        calls, replies = fake_upstream
        replies["analyze_codebase"] = {
            "status": "error",
            "message": "kuzu boot failed",
        }
        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )
        assert result["ingested"] is False
        assert result["reason"] == "upstream_mcp_unreachable"
        assert "kuzu boot failed" in result["error"]
        # Cache must not have been written.
        assert ingest_helpers.find_cached_graph(fake_store, "/tmp/myproj") is None

    @pytest.mark.asyncio
    async def test_file_attribution_uses_containment_not_qn_split(
        self, fake_store, fake_upstream, no_wiki
    ):
        """Files must come from (:File)-[]->(:symbol) edges, not from
        splitting qualified_name. Critical for non-Python codebases
        (Rust qns like ``crate::module::Type::method`` have no file
        prefix, so qn-split would fabricate a fake path).
        """
        calls, replies = fake_upstream
        replies["analyze_codebase"] = {"graph_path": "/tmp/graph"}
        replies["query_graph"] = [
            (
                _re(r"MATCH \(n:Function\)(?!-)"),
                {
                    "columns": [
                        "qualified_name",
                        "name",
                        "start_line",
                        "end_line",
                        "visibility",
                    ],
                    "rows": [
                        # Rust-style qn: head segment "crate" is NOT a file path.
                        ["crate::auth::login", "login", 1, 10, "pub"],
                        # Symbol with no containment edge AND head matches
                        # no known file → file should stay None.
                        ["nowhere::orphan", "orphan", 1, 5, ""],
                    ],
                },
            ),
            (_re(r"MATCH \(n:Method\)(?!-)"), {"columns": [], "rows": []}),
            (_re(r"MATCH \(n:Struct\)(?!-)"), {"columns": [], "rows": []}),
            (
                _re(r"MATCH \(f:File\)-\[\]->\(n:Function\|Method\|Struct\)"),
                {
                    "columns": ["file_path", "qn"],
                    "rows": [["src/auth.rs", "crate::auth::login"]],
                },
            ),
            (
                _re(r"MATCH \(f:File\)(?!-)"),
                {
                    "columns": ["path", "name", "extension", "size_bytes"],
                    "rows": [["src/auth.rs", "auth.rs", "rs", 200]],
                },
            ),
            (
                _re(r"MATCH \(a:Function\)-\[\]->\(b:Function\|Method\|Struct\)"),
                {"columns": [], "rows": []},
            ),
            (
                _re(r"MATCH \(a:Method\)-\[\]->\(b:Function\|Method\|Struct\)"),
                {"columns": [], "rows": []},
            ),
            (
                _re(r"MATCH \(a:Struct\)-\[\]->\(b:Function\|Method\|Struct\)"),
                {"columns": [], "rows": []},
            ),
        ]
        replies["get_processes"] = {"processes": []}

        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )
        assert result["ingested"] is True
        # 2 symbols (login attributed via containment, orphan unattributed) + 1 file
        assert result["memories_written"] == 3
        # Verify the login symbol got the authoritative path, not "crate".
        login_mem = next(
            m for m in fake_store.memories if "crate::auth::login" in m["content"]
        )
        assert "File: src/auth.rs" in login_mem["content"]
        # Orphan should not have a "File:" line at all.
        orphan_mem = next(
            m for m in fake_store.memories if "nowhere::orphan" in m["content"]
        )
        assert "File:" not in orphan_mem["content"]

    @pytest.mark.asyncio
    async def test_cypher_error_surfaces_as_diagnostic(
        self, fake_store, fake_upstream, no_wiki
    ):
        """Per-query upstream errors must surface in the response, not be
        swallowed by a broad except."""
        calls, replies = fake_upstream
        replies["analyze_codebase"] = {"graph_path": "/tmp/graph"}
        replies["query_graph"] = [
            (
                _re(r"MATCH \(n:Function\)(?!-)"),
                {
                    "status": "error",
                    "message": "binder exception: bad query",
                },
            ),
        ]
        replies["get_processes"] = {"processes": []}

        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )

        assert result["ingested"] is True
        assert "diagnostics" in result
        assert any("Function" in d for d in result["diagnostics"])
