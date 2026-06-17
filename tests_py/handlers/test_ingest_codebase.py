"""Tests for ingest_codebase — fake the upstream MCP client + the memory store."""

from __future__ import annotations

import re

import pytest

from mcp_server.handlers import ingest_codebase as icb
from mcp_server.handlers import ingest_codebase_pages as icb_pages
from mcp_server.handlers import ingest_helpers
from tests_py.conftest import _TEST_DB_URL, _USE_PG  # type: ignore

# The entity/edge writers now stream through PostgreSQL staging tables, so the
# write-asserting tests need a live DB. The schema migration (the LOWER(name)
# index + the directed-edge UNIQUE index that ON CONFLICT requires) must be
# present; apply it here so the test is self-contained.
_INGEST_MIGRATIONS = [
    "CREATE INDEX IF NOT EXISTS idx_entities_lower_name ON entities (LOWER(name))",
    """DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_indexes
                       WHERE indexname = 'uq_relationships_directed') THEN
            DELETE FROM relationships r USING (
                SELECT source_entity_id, target_entity_id, relationship_type,
                       MIN(id) AS keep_id FROM relationships
                GROUP BY source_entity_id, target_entity_id, relationship_type
                HAVING COUNT(*) > 1) dup
            WHERE r.source_entity_id = dup.source_entity_id
              AND r.target_entity_id = dup.target_entity_id
              AND r.relationship_type = dup.relationship_type
              AND r.id <> dup.keep_id;
            CREATE UNIQUE INDEX uq_relationships_directed
                ON relationships (source_entity_id, target_entity_id,
                                  relationship_type);
        END IF;
    END $$;""",
]


class _FakeStore:
    """In-memory memo cache + a real batch_pool for the staging write path.

    The graph-path memo (memoise/find_cached_graph) stays in-memory so the
    cache/error tests need no DB; ``batch_pool`` is a real pool opened lazily
    against the test DB, touched only when there are actual rows to write.
    """

    def __init__(self):
        import threading

        self.memories: list[dict] = []
        self._memo: dict[str, str] = {}
        self._pool = None
        self._pool_lock = threading.Lock()

    @property
    def batch_pool(self):
        with self._pool_lock:
            if self._pool is None:
                import psycopg
                from psycopg_pool import ConnectionPool

                self._pool = ConnectionPool(
                    conninfo=_TEST_DB_URL,
                    min_size=1,
                    max_size=4,
                    kwargs={
                        "autocommit": True,
                        "row_factory": psycopg.rows.dict_row,
                    },
                    open=True,
                )
        return self._pool

    def close_pool(self):
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def insert_memory(self, data: dict) -> int:
        mid = 1000 + len(self.memories)
        data["id"] = mid
        self.memories.append(data)
        return mid

    def get_all_memories_for_decay(self) -> list[dict]:
        return list(self.memories)


def _apply_ingest_migrations_and_clean():
    import psycopg

    with psycopg.connect(_TEST_DB_URL, autocommit=True) as conn:
        for stmt in _INGEST_MIGRATIONS:
            conn.execute(stmt)
        conn.execute("TRUNCATE entities, relationships RESTART IDENTITY CASCADE")


def _pg_entity_names() -> set[str]:
    import psycopg

    with psycopg.connect(_TEST_DB_URL, autocommit=True) as conn:
        rows = conn.execute("SELECT name FROM entities").fetchall()
    return {r[0] for r in rows}


@pytest.fixture
def fake_store(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(icb, "_get_store", lambda: store)
    yield store
    store.close_pool()


# Cypher pattern → reply for the fake upstream. Tests register a list
# of (compiled_regex, payload) tuples; the first regex that fully
# matches the cypher query wins. Regex routing avoids the substring-
# ordering footgun in earlier mock generations.
def _route_cypher(routes: list[tuple[re.Pattern[str], dict]], cypher: str) -> dict:
    # Simulate Kuzu SKIP/LIMIT pagination: a query that skips past the first
    # page returns no rows (end of data). Without this the fixed-payload mock
    # would return the same page for every offset and the paged symbol loop
    # would never terminate. Real Kuzu returns empty once SKIP exceeds the row
    # count.
    skip = re.search(r"SKIP\s+(\d+)", cypher)
    if skip and int(skip.group(1)) > 0:
        return {"rows": [], "columns": []}
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
    @pytest.mark.skipif(not _USE_PG, reason="staging write path needs live PG")
    @pytest.mark.asyncio
    async def test_happy_path_writes_memories_entities_edges_and_pages(
        self, fake_store, fake_upstream, no_wiki
    ):
        _apply_ingest_migrations_and_clean()
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
            (
                _re(r"ParticipatesIn_Function_Process"),
                {
                    "columns": ["qn"],
                    "rows": [["src/a.py::foo"], ["src/a.py::bar"]],
                },
            ),
            (
                _re(r"ParticipatesIn_Method_Process"),
                {"columns": [], "rows": []},
            ),
        ]
        # Real upstream shape (automatised-pipeline do_get_processes):
        # processes carry node_count/depth, never symbols/symbol_count.
        replies["get_processes"] = {
            "processes": [
                {
                    "name": "main",
                    "entry_point": "src/main.py::main",
                    "entry_kind": "main",
                    "depth": 2,
                    "node_count": 7,
                }
            ],
            "truncated": False,
        }

        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True}
        )

        assert result["ingested"] is True
        assert result["graph_path"] == "/tmp/graph"
        assert (
            "memories_written" not in result
        )  # symbols → entities only, no memory rows
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
        self, fake_store, fake_upstream, no_wiki, tmp_path
    ):
        calls, replies = fake_upstream
        # The cached graph must actually exist on disk to be reused. A memo
        # whose graph was deleted is (correctly) ignored — see the dead-graph
        # test below. source: ingest self-heal Jun-2026.
        graph_dir = tmp_path / "existing-graph"
        graph_dir.mkdir()
        (graph_dir / "data.kz").write_text("x")
        ingest_helpers.memoise_graph_path(fake_store, "/tmp/myproj", str(graph_dir))
        replies["query_graph"] = []
        replies["get_processes"] = {"processes": []}

        result = await icb.handler({"project_path": "/tmp/myproj"})

        assert result["ingested"] is True
        assert result["graph_path"] == str(graph_dir)
        assert result["analyze"]["reused_cached"] is True
        tools_called = [tool for (_, tool, _) in calls]
        assert "analyze_codebase" not in tools_called

    @pytest.mark.asyncio
    async def test_dead_cached_graph_triggers_reanalyze(
        self, fake_store, fake_upstream, no_wiki, tmp_path
    ):
        """Self-heal at the handler boundary: a memo whose graph was deleted
        must NOT be reused — the handler re-analyses instead of silently
        projecting an empty graph. source: ingest staleness bug Jun-2026."""
        calls, replies = fake_upstream
        # Memoise a path that does NOT exist on disk (graph was cleaned).
        ingest_helpers.memoise_graph_path(
            fake_store, "/tmp/myproj", str(tmp_path / "deleted-graph")
        )
        replies["analyze_codebase"] = {
            "graph_path": str(tmp_path / "fresh"),
            "node_count": 0,
        }
        replies["query_graph"] = []
        replies["get_processes"] = {"processes": []}

        result = await icb.handler({"project_path": "/tmp/myproj"})

        assert result["ingested"] is True
        assert result["analyze"]["reused_cached"] is False
        tools_called = [tool for (_, tool, _) in calls]
        assert "analyze_codebase" in tools_called


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
    @pytest.mark.skipif(not _USE_PG, reason="staging write path needs live PG")
    async def test_file_attribution_uses_containment_not_qn_split(
        self, fake_store, fake_upstream, no_wiki
    ):
        """Files must come from (:File)-[]->(:symbol) edges, not from
        splitting qualified_name. Critical for non-Python codebases
        (Rust qns like ``crate::module::Type::method`` have no file
        prefix, so qn-split would fabricate a fake path).
        """
        _apply_ingest_migrations_and_clean()
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
        assert (
            "memories_written" not in result
        )  # symbols → entities only, no memory rows
        # Symbols are stored as KG entities (name = qualified_name), resolved
        # server-side. Both the file-attributed symbol and the orphan are
        # written; the orphan keeps file=None but is still an entity.
        names = _pg_entity_names()
        assert "crate::auth::login" in names
        assert "nowhere::orphan" in names
        assert "src/auth.rs" in names  # the file is an entity too
        fake_store.close_pool()

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


class TestUpstreamPagination:
    """Regressions for the 2026-06-11 silent-truncation RCA.

    Upstream bounds every response two ways: LIMIT 500 injected into
    LIMIT-less Cypher, and byte-budget paging (truncated/next_offset).
    Ignoring either silently truncated ingests (~887/4669 call edges,
    500/1233 files).
    """

    @pytest.mark.asyncio
    async def test_run_query_drains_byte_budget_pages(self, monkeypatch):
        from mcp_server.handlers import ingest_codebase_cypher as cyp

        pages = {
            0: {
                "rows": [["a"], ["b"]],
                "columns": ["qn"],
                "truncated": True,
                "next_offset": 2,
            },
            2: {"rows": [["c"]], "columns": ["qn"], "truncated": False},
        }
        seen_offsets: list[int] = []

        async def _call(server, tool, args):
            seen_offsets.append(args["offset"])
            return pages[args["offset"]]

        monkeypatch.setattr(cyp, "call_upstream", _call)
        result, err = await cyp._run_query("/g", "MATCH (n) RETURN n LIMIT 10")
        assert err is None
        assert result["rows"] == [["a"], ["b"], ["c"]]
        assert seen_offsets == [0, 2]

    @pytest.mark.asyncio
    async def test_run_query_rejects_non_advancing_cursor(self, monkeypatch):
        from mcp_server.handlers import ingest_codebase_cypher as cyp

        async def _call(server, tool, args):
            return {
                "rows": [["a"]],
                "truncated": True,
                "next_offset": 0,  # never advances — must not spin forever
            }

        monkeypatch.setattr(cyp, "call_upstream", _call)
        result, err = await cyp._run_query("/g", "MATCH (n) RETURN n LIMIT 10")
        # On any upstream error _run_query returns an empty dict (never None)
        # plus a populated message — callers bail on err, not on result.
        assert result == {}
        assert "non-advancing" in err

    @pytest.mark.asyncio
    async def test_fetch_files_pages_past_injected_limit(self, monkeypatch):
        """A LIMIT-less query is capped at 500 rows upstream; fetch_files
        must page with explicit SKIP/LIMIT to recover all files."""
        from mcp_server.handlers import ingest_codebase_cypher as cyp

        total = 733

        async def _call(server, tool, args):
            q = args["query"]
            skip = int(re.search(r"SKIP (\d+)", q).group(1))
            limit = int(re.search(r"LIMIT (\d+)", q).group(1))
            n = max(0, min(limit, total - skip))
            rows = [[f"f{skip + i}.py", "n", "py", 1] for i in range(n)]
            return {
                "rows": rows,
                "columns": ["path", "name", "extension", "size_bytes"],
                "truncated": False,
            }

        monkeypatch.setattr(cyp, "call_upstream", _call)
        files, diag = await cyp.fetch_files("/g", limit=None)
        assert diag == []
        assert len(files) == total
        assert files[0]["path"] == "f0.py" and files[-1]["path"] == "f732.py"

    @pytest.mark.asyncio
    async def test_pull_processes_follows_cursor(self, monkeypatch):
        async def _call(server, tool, args):
            if args.get("offset", 0) == 0:
                return {
                    "processes": [{"name": "p1", "node_count": 1}],
                    "truncated": True,
                    "next_offset": 1,
                }
            return {
                "processes": [{"name": "p2", "node_count": 2}],
                "truncated": False,
            }

        monkeypatch.setattr(icb, "call_upstream", _call)
        procs = await icb._pull_processes("/g", None)
        assert [p["name"] for p in procs] == ["p1", "p2"]


class TestProcessPageRendering:
    def test_node_count_drives_skip_filter(self, no_wiki):
        """get_processes emits node_count (never symbols/symbol_count);
        a reader keyed on the wrong field skipped every process as empty
        and zero wiki pages were ever written."""
        written = icb_pages.write_process_pages(
            [
                {
                    "name": "empty",
                    "entry_point": "e0",
                    "entry_kind": "main",
                    "depth": 0,
                    "node_count": 0,
                },
                {
                    "name": "real_flow",
                    "entry_point": "e1",
                    "entry_kind": "main",
                    "depth": 3,
                    "node_count": 12,
                },
            ]
        )
        assert written == ["reference/codebase/real-flow.md"]
        rel, content = no_wiki[0]
        assert "**Symbols in flow:** 12" in content
        assert "**BFS depth:** 3" in content

    def test_symbols_overflow_note_uses_node_count(self, no_wiki):
        proc = {
            "name": "big",
            "entry_point": "e2",
            "entry_kind": "main",
            "depth": 1,
            "node_count": 80,
            "symbols": [f"m::f{i}" for i in range(50)],
        }
        icb_pages.write_process_pages([proc])
        _, content = no_wiki[0]
        assert "- … and 30 more." in content


class TestSymbolPageStride:
    @pytest.mark.asyncio
    async def test_paging_loop_visits_every_symbol_without_gaps(self, monkeypatch):
        """The caller must advance by symbol_page_stride(page_size), not
        page_size — the old stride skipped per-label rows between
        page_size//3 and page_size in every window (≈2000 of 3645
        Functions on the Cortex graph)."""
        from mcp_server.handlers import ingest_codebase_cypher as cyp

        label_rows = {
            "Function": [f"fn_{i}" for i in range(7)],
            "Method": [f"m_{i}" for i in range(2)],
            "Struct": [],
        }

        async def _call(server, tool, args):
            q = args["query"]
            label = re.search(r"MATCH \(n:(\w+)\)", q).group(1)
            skip = int(re.search(r"SKIP (\d+)", q).group(1))
            limit = int(re.search(r"LIMIT (\d+)", q).group(1))
            window = label_rows[label][skip : skip + limit]
            return {
                "columns": [
                    "qualified_name",
                    "name",
                    "start_line",
                    "end_line",
                    "visibility",
                ],
                "rows": [[qn, qn, 1, 2, ""] for qn in window],
                "truncated": False,
            }

        monkeypatch.setattr(cyp, "call_upstream", _call)

        page_size = 9  # stride = 3
        seen: list[str] = []
        offset = 0
        while True:
            page, diag = await cyp.fetch_symbols_page(
                "/g", offset=offset, page_size=page_size
            )
            assert diag == []
            if not page:
                break
            seen.extend(s["qualified_name"] for s in page)
            offset += cyp.symbol_page_stride(page_size)

        assert sorted(seen) == sorted(label_rows["Function"] + label_rows["Method"])
        assert len(seen) == len(set(seen))  # no duplicates either
