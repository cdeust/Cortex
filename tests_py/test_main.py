"""Tests for mcp_server.__main__ entry point."""

import signal
from unittest.mock import patch

import pytest

from mcp_server.__main__ import main, _shutdown, mcp


class TestMain:
    def test_main_is_callable(self):
        assert callable(main)

    def test_main_registers_signal_handlers_and_runs(self):
        with (
            patch("mcp_server.__main__.signal.signal") as mock_signal,
            patch.object(mcp, "run", side_effect=None) as mock_run,
        ):
            main()

            # Should register SIGTERM and SIGINT handlers
            calls = mock_signal.call_args_list
            sig_nums = [c[0][0] for c in calls]
            assert signal.SIGTERM in sig_nums
            assert signal.SIGINT in sig_nums

            # Should call mcp.run with stdio transport
            mock_run.assert_called_once_with(transport="stdio")

    def test_mcp_server_has_tools(self):
        """FastMCP instance should have all 17 tools registered."""
        import asyncio

        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        assert "query_methodology" in tool_names
        assert "detect_domain" in tool_names
        assert "rebuild_profiles" in tool_names
        assert "list_domains" in tool_names
        assert "record_session_end" in tool_names
        assert "get_methodology_graph" in tool_names
        assert "open_visualization" in tool_names
        assert "explore_features" in tool_names
        assert "run_pipeline" in tool_names
        assert "remember" in tool_names
        assert "recall" in tool_names
        assert "memory_stats" in tool_names
        assert "checkpoint" in tool_names
        assert "consolidate" in tool_names
        assert "narrative" in tool_names
        assert "import_sessions" in tool_names
        assert "codebase_analyze" in tool_names
        assert "wiki_write" in tool_names
        assert "wiki_read" in tool_names
        assert "wiki_list" in tool_names
        assert "wiki_link" in tool_names
        assert "wiki_adr" in tool_names
        assert "wiki_reindex" in tool_names
        assert len(tool_names) == 40

    def test_mcp_server_name_and_version(self):
        assert mcp.name == "methodology-agent"
        assert mcp.version == "1.0.0"

    def test_mcp_server_has_instructions(self):
        assert mcp.instructions is not None
        assert "query_methodology" in mcp.instructions


class TestShutdown:
    def test_shutdown_calls_close_all_and_shutdown_server(self):
        with (
            patch("mcp_server.__main__.close_all") as mock_close,
            patch("mcp_server.__main__.shutdown_server") as mock_shutdown,
            pytest.raises(SystemExit) as exc_info,
        ):
            _shutdown()
        mock_close.assert_called_once()
        mock_shutdown.assert_called_once()
        assert exc_info.value.code == 0

    def test_shutdown_with_signal_args(self):
        with (
            patch("mcp_server.__main__.close_all"),
            patch("mcp_server.__main__.shutdown_server"),
            pytest.raises(SystemExit),
        ):
            _shutdown(sig=signal.SIGTERM, frame=None)

    def test_shutdown_exits_with_zero(self):
        with (
            patch("mcp_server.__main__.close_all"),
            patch("mcp_server.__main__.shutdown_server"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _shutdown()
        assert exc_info.value.code == 0
