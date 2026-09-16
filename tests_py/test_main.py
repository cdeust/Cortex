"""Tests for mcp_server.__main__ entry point."""

import asyncio
import signal
from unittest.mock import patch

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server.__main__ import (
    main,
    _shutdown,
    mcp,
    register_all,
)


# The 3 upstream-integration tools, conditionally registered by upstream
# availability (source: MCP Directory submission decision 2026-06-19).
_UPSTREAM_TOOLS = {"ingest_codebase", "change_impact", "ingest_prd"}

# Tools that register without any upstream: the core memory and profiling
# set, the wiki authoring set, and the ones added since the 2026-07-12
# re-derivation of the baseline.
_NO_UPSTREAM_TOOLS = {
    "query_methodology",
    "detect_domain",
    "rebuild_profiles",
    "list_domains",
    "record_session_end",
    "explore_features",
    "remember",
    "recall",
    "memory_stats",
    "checkpoint",
    "consolidate",
    "narrative",
    "import_sessions",
    "codebase_analyze",  # native AST — no upstream needed
    "unified_search",  # ap_bridge degrades to native AST
    "wiki_verify",
    "get_telemetry",
    "wiki_write",
    "wiki_rename",
    "wiki_migrate",
    "why",  # blame path T3: the receipt resolver
    "ingest_findings",  # INC5.1: disk-based AP findings consumer
    "lesson_promotion",  # M-D6 (7.6): PG-only
    "curate_distill",  # INC7.8/M-D8: distillation dossiers
    "get_grooming_health",  # INC G-4: grooming backlog telemetry
    "check_setup",  # issue #115: doctor.py facade
    "ingest_document",  # issue #192: offline document ingest
    "wiki_get_draft",  # issue #579: Path B draft refinement
    "wiki_refine_draft",
    "predict",  # issue #597: prediction records
    "resolve_prediction",
    "calibration",
}

# Extracted to the cortex-viz MCP — never registered by this server.
_EXTRACTED_TOOLS = {
    "get_methodology_graph",
    "open_visualization",
    "query_workflow_graph",
}


def _tool_names(*, codebase: bool, prd: bool) -> set[str]:
    """Build a fresh server with explicit availability flags; return tool names.

    Deterministic — independent of whether ai-architect-mcp-codebase / prd-spec-gen
    happen to be installed on the machine running the test.
    """
    server = MCPServer(name="test", version="0.0.0")
    register_all(server, codebase=codebase, prd=prd)
    return {t.name for t in asyncio.run(server.list_tools())}


class TestMain:
    def test_main_is_callable(self):
        assert callable(main)

    def test_main_registers_signal_handlers_and_runs(self):
        # main() drives stdio via mcp.run_stdio_async directly now (was
        # mcp_server.infrastructure.stdio_transport.run_stdio_drained, a
        # workaround for a FastMCP-only defect that mcp 2.0.0's own
        # dispatcher no longer has -- see __main__.py's main() docstring
        # comment for the empirical verification). anyio.run is what
        # main() calls; assert THAT call, with the SDK-native driver.
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

            # Should drive stdio via the SDK's own run_stdio_async, not a
            # Cortex-side wrapper.
            mock_anyio_run.assert_called_once_with(mcp.run_stdio_async)

    def test_standalone_baseline_is_57_tools(self):
        """With no upstream available, exactly the 57 standalone tools register.

        57 = the 49 tools re-derived 2026-07-12 (fix/bare-container-contract,
        live DB-less `tools/list` round-trip) + `wiki_migrate` (FS→PG wiki
        parity, commit 4be298a3) + `check_setup` (doctor.py facade, issue
        #115) + `ingest_document` (offline .docx / Confluence export ingest,
        issue #192 — file-only, no upstream to gate on) + `wiki_get_draft`
        and `wiki_refine_draft` (Path B draft refinement, defined since
        ADR-0467 and exposed by ADR-1066, issue #579) + `predict`,
        `resolve_prediction` and `calibration` (prediction records and their
        Brier score, ADR-1076, issue #597). The 3
        upstream-integration tools (ingest_codebase, change_impact,
        ingest_prd) MUST NOT be advertised — every advertised tool then works
        out of the box.
        source: MCP Directory submission decision 2026-06-19.
        """
        names = _tool_names(codebase=False, prd=False)
        # The upstream-integration tools are gated OFF.
        assert names.isdisjoint(_UPSTREAM_TOOLS)
        assert len(names) == 57

    def test_standalone_surface_holds_every_no_upstream_tool(self):
        """What that baseline is made of, and what it must never hold."""
        names = _tool_names(codebase=False, prd=False)
        assert _NO_UPSTREAM_TOOLS <= names
        assert names.isdisjoint(_EXTRACTED_TOOLS)

    def test_with_upstreams_registers_60_tools(self):
        """When both upstreams are available, the 3 integration tools register."""
        names = _tool_names(codebase=True, prd=True)
        assert _UPSTREAM_TOOLS <= names
        assert len(names) == 60

    def test_codebase_only_adds_two_tools(self):
        """codebase upstream gates ingest_codebase + change_impact together."""
        names = _tool_names(codebase=True, prd=False)
        assert {"ingest_codebase", "change_impact"} <= names
        assert "ingest_prd" not in names
        assert len(names) == 59

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
