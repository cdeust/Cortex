"""Tests for mcp_server.handlers.open_visualization — unified 3D graph launcher."""

import asyncio
from unittest.mock import patch, MagicMock

from mcp_server.handlers import open_visualization
from mcp_server.handlers.open_visualization import handler


class TestOpenVisualizationSchema:
    def test_exports_schema_and_handler(self):
        assert open_visualization.schema is not None
        assert open_visualization.handler is not None
        assert callable(open_visualization.handler)
        assert open_visualization.schema["description"]
        assert open_visualization.schema["inputSchema"]

    def test_domain_is_optional(self):
        required = open_visualization.schema["inputSchema"].get("required", [])
        assert "domain" not in required


class TestOpenVisualizationHandler:
    def test_returns_url(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.start_unified_viz_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.subprocess.run"),
        ):
            result = asyncio.run(handler({}))

        assert result["url"] == "http://localhost:3458"
        assert "localhost" in result["message"]

    def test_default_args_none(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.start_unified_viz_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.subprocess.run"),
        ):
            result = asyncio.run(handler(None))
        assert result["url"] == "http://localhost:3458"

    def test_passes_getters_to_server(self):
        mock_start = MagicMock(return_value="http://localhost:3458")
        with (
            patch(
                "mcp_server.handlers.open_visualization.start_unified_viz_server",
                mock_start,
            ),
            patch("mcp_server.handlers.open_visualization.subprocess.run"),
        ):
            asyncio.run(handler({}))

        mock_start.assert_called_once()
        kwargs = mock_start.call_args[1]
        assert "profiles_getter" in kwargs
        assert "store_getter" in kwargs

    def test_calls_subprocess_open(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.start_unified_viz_server",
                return_value="http://localhost:5555",
            ),
            patch("mcp_server.handlers.open_visualization.subprocess.run") as mock_run,
        ):
            asyncio.run(handler({}))
        mock_run.assert_called_once_with(
            ["open", "http://localhost:5555"], capture_output=True, check=False
        )

    def test_falls_back_to_xdg_open_on_exception(self):
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FileNotFoundError("open not found")
            return MagicMock()

        with (
            patch(
                "mcp_server.handlers.open_visualization.start_unified_viz_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.subprocess.run",
                side_effect=side_effect,
            ) as mock_run,
        ):
            result = asyncio.run(handler({}))

        assert result["url"] == "http://localhost:5555"
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[1][0][0] == ["xdg-open", "http://localhost:5555"]

    def test_handles_both_open_commands_failing(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.start_unified_viz_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.subprocess.run",
                side_effect=FileNotFoundError("not found"),
            ),
        ):
            result = asyncio.run(handler({}))
        assert result["url"] == "http://localhost:5555"
