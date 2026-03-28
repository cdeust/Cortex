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
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            result = asyncio.run(handler({}))

        assert result["url"] == "http://localhost:3458"
        assert "localhost" in result["message"]

    def test_default_args_none(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:3458",
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            result = asyncio.run(handler(None))
        assert result["url"] == "http://localhost:3458"

    def test_launches_unified_server_type(self):
        mock_launch = MagicMock(return_value="http://localhost:3458")
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                mock_launch,
            ),
            patch("mcp_server.handlers.open_visualization.open_in_browser"),
        ):
            asyncio.run(handler({}))

        mock_launch.assert_called_once_with("unified")

    def test_opens_browser(self):
        with (
            patch(
                "mcp_server.handlers.open_visualization.launch_server",
                return_value="http://localhost:5555",
            ),
            patch(
                "mcp_server.handlers.open_visualization.open_in_browser",
            ) as mock_open,
        ):
            asyncio.run(handler({}))
        mock_open.assert_called_once_with("http://localhost:5555")
