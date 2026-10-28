"""Boundary contracts for upstream graph rows, failures and graph provenance."""

import json
from unittest.mock import AsyncMock

import pytest

from mcp_server.errors import McpConnectionError
from mcp_server.handlers import ingest_codebase_cypher as cypher


@pytest.fixture
def upstream(monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(cypher, "call_upstream", call)
    return call


@pytest.mark.parametrize(
    ("qualified", "candidates"),
    [
        ("", []),
        ("unqualified", []),
        ("src/lib.rs::run", ["src/lib.rs"]),
        ("service.auth::Login", ["service/auth.py"]),
        (
            "pkg::module::Class::method",
            ["pkg/module/Class.py", "pkg/module.py", "pkg.py"],
        ),
    ],
)
def test_orphan_symbol_candidates_preserve_file_names_and_module_order(
    qualified, candidates
):
    assert cypher.file_path_from_qn(qualified) == candidates


@pytest.mark.asyncio
async def test_unexpected_mcp_payload_is_a_diagnostic_not_empty_success(upstream):
    upstream.return_value = {"content": [{"type": "text", "text": json.dumps([])}]}
    result, error = await cypher._run_query("/graph/requested", "RETURN 1")
    assert result == {}
    assert error == "unexpected payload type: list"
    upstream.assert_awaited_once_with(
        "codebase",
        "query_graph",
        {"graph_path": "/graph/requested", "query": "RETURN 1", "offset": 0},
    )


@pytest.mark.asyncio
async def test_symbol_total_sums_each_label_and_keeps_requested_graph(upstream):
    upstream.side_effect = [{"rows": [[2]]}, {"rows": [["3"]]}, {"rows": [[0]]}]
    assert await cypher.fetch_symbols_total("/graph/count") == 5
    queries = [call.args[2] for call in upstream.await_args_list]
    assert [q["query"] for q in queries] == [
        f"MATCH (n:{label}) RETURN COUNT(n) AS c"
        for label in ("Function", "Method", "Struct")
    ]
    assert all(q["graph_path"] == "/graph/count" for q in queries)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        {"rows": []},
        {"rows": [[]]},
        {"rows": [[None]]},
        {"status": "error", "message": "missing graph"},
        McpConnectionError("offline"),
    ],
)
async def test_symbol_total_failure_is_indeterminate_never_zero(upstream, reply):
    upstream.side_effect = [reply]
    assert await cypher.fetch_symbols_total("/graph") is None
    assert upstream.await_count == 1


@pytest.mark.asyncio
async def test_symbol_page_keeps_partial_records_and_names_failed_label(upstream):
    upstream.side_effect = [
        McpConnectionError("connection lost"),
        {"columns": ["name", "start_line"], "rows": [["Login", 7], [""]]},
        {"rows": [["auth::Token", "Token", 1, 9, "public"]]},
    ]
    symbols, diagnostics = await cypher.fetch_symbols_page(
        "/graph", offset=6, page_size=9
    )
    assert symbols == [
        {
            "qualified_name": "Login",
            "name": "Login",
            "kind": "Method",
            "file": None,
            "start_line": 7,
            "end_line": None,
            "visibility": None,
        },
        {
            "qualified_name": "auth::Token",
            "name": "Token",
            "kind": "Struct",
            "file": None,
            "start_line": 1,
            "end_line": 9,
            "visibility": "public",
        },
    ]
    assert diagnostics == ["Function@6: McpConnectionError: connection lost"]
    assert all(
        call.args[2]["query"].endswith("SKIP 6 LIMIT 3")
        for call in upstream.await_args_list
    )


@pytest.mark.asyncio
async def test_call_edge_stream_advances_over_rejected_rows_and_continues_other_labels(
    upstream,
):
    upstream.side_effect = [
        {"rows": [["a", "a"], ["a", "b"]]},
        {"rows": [["short"], [None, "b"]]},
        {"rows": []},
        {"status": "error", "message": "Method unavailable"},
        {"rows": [["s", "b"]]},
    ]
    pages = [page async for page in cypher.iter_call_edges("/graph", page_size=2)]
    assert pages == [
        ([("a", "b")], []),
        ([], []),
        ([], []),
        ([], ["call-edges/Method@0: Method unavailable"]),
        ([("s", "b")], []),
    ]
    queries = [call.args[2]["query"] for call in upstream.await_args_list]
    assert [q.rsplit("SKIP ", 1)[1] for q in queries] == [
        "0 LIMIT 2",
        "2 LIMIT 2",
        "4 LIMIT 2",
        "0 LIMIT 2",
        "0 LIMIT 2",
    ]


@pytest.mark.asyncio
async def test_containment_uses_known_files_not_symbol_spelling(upstream):
    upstream.side_effect = [
        {"rows": [["src/auth.rs", "unrelated::module::Login"], ["unknown.py", "x"]]},
        {"rows": [["src/auth.rs"], ["src/auth.rs", None]]},
        {"rows": []},
    ]
    pages = [
        page
        async for page in cypher.iter_containment_edges("/graph", {"src/auth.rs"}, 2)
    ]
    assert pages == [
        ([("src/auth.rs", "unrelated::module::Login")], []),
        ([], []),
        ([], []),
    ]
    assert upstream.await_count == 3


@pytest.mark.asyncio
async def test_containment_empty_known_set_does_not_query_upstream(upstream):
    assert [
        page async for page in cypher.iter_containment_edges("/graph", set(), 2)
    ] == []
    upstream.assert_not_awaited()


@pytest.mark.asyncio
async def test_transport_failure_is_named_for_each_edge_stage(upstream):
    upstream.side_effect = McpConnectionError("offline")
    calls = [page async for page in cypher.iter_call_edges("/graph", 2)]
    assert calls == [
        ([], [f"call-edges/{label}@0: McpConnectionError: offline"])
        for label in ("Function", "Method", "Struct")
    ]
    containment = [
        page async for page in cypher.iter_containment_edges("/graph", {"a.py"}, 2)
    ]
    assert containment == [([], ["file-containment@0: McpConnectionError: offline"])]


@pytest.mark.asyncio
async def test_containment_upstream_error_is_not_reported_as_exhaustion(upstream):
    upstream.return_value = {"status": "error", "message": "binder failure"}
    assert [
        page async for page in cypher.iter_containment_edges("/graph", {"a.py"}, 2)
    ] == [([], ["file-containment@0: binder failure"])]


@pytest.mark.asyncio
async def test_file_limit_stops_without_overfetch_and_partial_columns_stay_unknown(
    upstream,
):
    upstream.return_value = {"rows": [["src/a.py"], ["src/b.ts", "b.ts", "ts", 8]]}
    files, diagnostics = await cypher.fetch_files("/graph", limit=2)
    assert files == [
        {"path": "src/a.py", "name": None, "extension": None, "size_bytes": None},
        {"path": "src/b.ts", "name": "b.ts", "extension": "ts", "size_bytes": 8},
    ]
    assert diagnostics == []
    assert upstream.await_count == 1
    assert upstream.await_args.args[2]["query"].endswith("SKIP 0 LIMIT 2")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [McpConnectionError("offline"), {"status": "error", "message": "graph closed"}],
)
async def test_file_failure_preserves_prior_page_and_identifies_offset(
    upstream, failure
):
    upstream.side_effect = [{"rows": [[f"src/f{i}.py"] for i in range(500)]}, failure]
    files, diagnostics = await cypher.fetch_files("/graph", limit=None)
    assert len(files) == 500
    assert files[-1]["path"] == "src/f499.py"
    assert len(diagnostics) == 1
    assert diagnostics[0].startswith("files@500: ")
    assert (
        str(failure) in diagnostics[0]
        if isinstance(failure, Exception)
        else "graph closed" in diagnostics[0]
    )


@pytest.mark.asyncio
async def test_file_rows_without_identity_are_excluded(upstream):
    upstream.return_value = {"rows": [[], [None], ["valid.py"]]}
    files, diagnostics = await cypher.fetch_files("/graph", limit=None)
    assert [item["path"] for item in files] == ["valid.py"]
    assert diagnostics == []


@pytest.mark.asyncio
async def test_process_membership_escapes_entry_id_and_caps_combined_labels(upstream):
    upstream.side_effect = [
        {"rows": [[], [None], ["fn-a"], ["fn-b"]]},
        {"rows": [["method-a"], ["method-b"]]},
    ]
    symbols, diagnostics = await cypher.fetch_process_symbols(
        "/graph", "entry'quoted", 3
    )
    assert symbols == ["fn-a", "fn-b", "method-a"]
    assert diagnostics == []
    queries = [call.args[2]["query"] for call in upstream.await_args_list]
    assert all("p.entry_point_id = 'entry\\'quoted'" in q for q in queries)
    assert "ParticipatesIn_Function_Process" in queries[0]
    assert "ParticipatesIn_Method_Process" in queries[1]


@pytest.mark.asyncio
async def test_process_membership_reports_transport_and_upstream_failures(upstream):
    upstream.side_effect = [
        McpConnectionError("offline"),
        {"status": "error", "message": "bad query"},
    ]
    symbols, diagnostics = await cypher.fetch_process_symbols("/graph", "entry", 3)
    assert symbols == []
    assert diagnostics == [
        "process-symbols/Function: McpConnectionError: offline",
        "process-symbols/Method: bad query",
    ]


@pytest.mark.asyncio
async def test_programming_errors_propagate_outside_transport_boundary(upstream):
    upstream.side_effect = RuntimeError("bug in upstream adapter")
    with pytest.raises(RuntimeError, match="bug in upstream adapter"):
        await cypher.fetch_symbols_total("/graph")
