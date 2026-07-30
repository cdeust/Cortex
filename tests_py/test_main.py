"""Tests for mcp_server.__main__ entry point."""

import asyncio
import signal
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from mcp_server.__main__ import main, _shutdown, mcp, register_all, run_stdio_drained


# The 3 upstream-integration tools, conditionally registered by upstream
# availability (source: MCP Directory submission decision 2026-06-19).
_UPSTREAM_TOOLS = {"ingest_codebase", "change_impact", "ingest_prd"}


def _tool_names(*, codebase: bool, prd: bool) -> set[str]:
    """Build a fresh server with explicit availability flags; return tool names.

    Deterministic — independent of whether automatised-pipeline / prd-spec-gen
    happen to be installed on the machine running the test.
    """
    server = FastMCP(name="test", version="0.0.0")
    register_all(server, codebase=codebase, prd=prd)
    return {t.name for t in asyncio.run(server.list_tools())}


class TestMain:
    def test_main_is_callable(self):
        assert callable(main)

    def test_main_registers_signal_handlers_and_runs(self):
        # Not mcp.run(transport="stdio"): main() drives stdio via
        # run_stdio_drained
        # (mcp_server/infrastructure/stdio_transport.py) instead, so that
        # a request dispatched from the last line of a
        # batch is drained before shutdown rather than losing its response
        # to stdin-EOF (see that module's docstring). anyio.run is what
        # main() calls now; assert THAT call, with the drained driver.
        with (
            patch("mcp_server.__main__.signal.signal") as mock_signal,
            patch("mcp_server.__main__.anyio.run") as mock_anyio_run,
        ):
            main()

            # Should register SIGTERM and SIGINT handlers
            calls = mock_signal.call_args_list
            sig_nums = [c[0][0] for c in calls]
            assert signal.SIGTERM in sig_nums
            assert signal.SIGINT in sig_nums

            # Should drive stdio via the drain-safe wrapper, not
            # mcp.run(transport="stdio") directly.
            mock_anyio_run.assert_called_once_with(run_stdio_drained, mcp)

    def test_standalone_baseline_is_52_tools(self):
        """With no upstream available, exactly the 52 standalone tools register.

        52 = the 49 tools re-derived 2026-07-12 (fix/bare-container-contract,
        live DB-less `tools/list` round-trip) + `wiki_migrate` (FS→PG wiki
        parity, commit 4be298a3) + `check_setup` (doctor.py facade, issue
        #115) + `ingest_document` (offline .docx / Confluence export ingest,
        issue #192 — file-only, no upstream to gate on). The 3
        upstream-integration tools (ingest_codebase, change_impact,
        ingest_prd) MUST NOT be advertised — every advertised tool then works
        out of the box.
        source: MCP Directory submission decision 2026-06-19.
        """
        names = _tool_names(codebase=False, prd=False)
        # Core memory / profiling / wiki tools are always present.
        assert "query_methodology" in names
        assert "detect_domain" in names
        assert "rebuild_profiles" in names
        assert "list_domains" in names
        assert "record_session_end" in names
        assert "explore_features" in names
        assert "remember" in names
        assert "recall" in names
        assert "memory_stats" in names
        assert "checkpoint" in names
        assert "consolidate" in names
        assert "narrative" in names
        assert "import_sessions" in names
        assert "codebase_analyze" in names  # native AST — no upstream needed
        assert "unified_search" in names  # ap_bridge degrades to native AST
        assert "wiki_verify" in names
        assert "get_telemetry" in names
        assert "wiki_write" in names
        assert "wiki_rename" in names
        assert "wiki_migrate" in names
        # Extracted to cortex-viz MCP — never registered here.
        assert "get_methodology_graph" not in names
        assert "open_visualization" not in names
        assert "query_workflow_graph" not in names
        # Blame path T3: the receipt resolver is a standalone tool.
        assert "why" in names
        # INC5.1: the AP findings consumer is disk-based, always registered.
        assert "ingest_findings" in names
        # M-D6 (7.6): lesson_promotion is PG-only, no upstream needed.
        assert "lesson_promotion" in names
        # INC7.8/M-D8: distillation dossiers, disk/DB only, no upstream.
        assert "curate_distill" in names
        # INC G-4: grooming backlog + staleness telemetry, PG-only, no
        # upstream needed.
        assert "get_grooming_health" in names
        # Issue #115: doctor.py facade, no upstream needed.
        assert "check_setup" in names
        # Issue #192: offline document ingest (.docx / Confluence export),
        # file-only, no upstream needed.
        assert "ingest_document" in names
        # The upstream-integration tools are gated OFF.
        assert names.isdisjoint(_UPSTREAM_TOOLS)
        assert len(names) == 52

    def test_with_upstreams_registers_55_tools(self):
        """When both upstreams are available, the 3 integration tools register."""
        names = _tool_names(codebase=True, prd=True)
        assert _UPSTREAM_TOOLS <= names
        assert len(names) == 55

    def test_codebase_only_adds_two_tools(self):
        """codebase upstream gates ingest_codebase + change_impact together."""
        names = _tool_names(codebase=True, prd=False)
        assert {"ingest_codebase", "change_impact"} <= names
        assert "ingest_prd" not in names
        assert len(names) == 54

    def test_mcp_server_name_and_version(self):
        assert mcp.name == "methodology-agent"
        assert mcp.version == "1.0.0"

    def test_mcp_server_has_instructions(self):
        assert mcp.instructions is not None
        assert "query_methodology" in mcp.instructions


class TestShutdown:
    def test_shutdown_calls_close_all(self):
        # HTTP viz-server shutdown moved to cortex-viz; _shutdown now only
        # closes the MCP client pool.
        with (
            patch("mcp_server.__main__.close_all") as mock_close,
            pytest.raises(SystemExit) as exc_info,
        ):
            _shutdown()
        mock_close.assert_called_once()
        assert exc_info.value.code == 0

    def test_shutdown_with_signal_args(self):
        with (
            patch("mcp_server.__main__.close_all"),
            pytest.raises(SystemExit),
        ):
            _shutdown(sig=signal.SIGTERM, frame=None)

    def test_shutdown_exits_with_zero(self):
        with (
            patch("mcp_server.__main__.close_all"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _shutdown()
        assert exc_info.value.code == 0
