"""Tests for mcp_server.infrastructure.mcp_client_pool — ported from mcp-client-pool.test.js."""

import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure import mcp_client_pool
from mcp_server.infrastructure.mcp_client_pool import (
    _load_server_config,
    get_client,
    close_client,
    close_all,
)


class TestLoadServerConfig:
    def test_raises_when_config_not_found(self):
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=None
        ):
            with pytest.raises(McpConnectionError, match="not found"):
                _load_server_config("some-server")

    def test_raises_when_no_servers_key(self):
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value={}
        ):
            with pytest.raises(McpConnectionError, match="not found"):
                _load_server_config("some-server")

    def test_raises_when_servers_is_empty(self):
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json",
            return_value={"servers": {}},
        ):
            with pytest.raises(McpConnectionError, match="not found"):
                _load_server_config("missing")

    def test_raises_for_unknown_server_name(self):
        config = {"servers": {"foo": {"command": "echo"}, "bar": {"command": "cat"}}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            with pytest.raises(McpConnectionError, match="not found.*Available"):
                _load_server_config("baz")

    def test_returns_server_config_when_found(self):
        server_cfg = {"command": "node", "args": ["server.js"]}
        config = {"servers": {"my-server": server_cfg}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            result = _load_server_config("my-server")
            assert result["command"] == "node"

    def test_resolves_env_var_interpolation(self):
        server_cfg = {
            "command": "node",
            "env": {"TOKEN": "${MY_TOKEN}", "PLAIN": "hello"},
        }
        config = {"servers": {"srv": server_cfg}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            with patch.dict(os.environ, {"MY_TOKEN": "secret123"}):
                result = _load_server_config("srv")
                assert result["env"]["TOKEN"] == "secret123"
                assert result["env"]["PLAIN"] == "hello"

    def test_env_var_interpolation_missing_var_resolves_empty(self):
        server_cfg = {"command": "node", "env": {"TOKEN": "${NONEXISTENT_VAR_XYZ}"}}
        config = {"servers": {"srv": server_cfg}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            # Ensure the var doesn't exist
            env = os.environ.copy()
            env.pop("NONEXISTENT_VAR_XYZ", None)
            with patch.dict(os.environ, env, clear=True):
                result = _load_server_config("srv")
                assert result["env"]["TOKEN"] == ""

    def test_env_var_interpolation_multiple_vars_in_one_value(self):
        server_cfg = {"command": "node", "env": {"URL": "${HOST}:${PORT}/api"}}
        config = {"servers": {"srv": server_cfg}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            with patch.dict(os.environ, {"HOST": "localhost", "PORT": "3000"}):
                result = _load_server_config("srv")
                assert result["env"]["URL"] == "localhost:3000/api"

    def test_no_env_block_is_fine(self):
        server_cfg = {"command": "node"}
        config = {"servers": {"srv": server_cfg}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            result = _load_server_config("srv")
            assert result["command"] == "node"

    def test_env_with_non_string_values_skipped(self):
        server_cfg = {"command": "node", "env": {"NUM": 42, "STR": "${VAR}"}}
        config = {"servers": {"srv": server_cfg}}
        with patch(
            "mcp_server.infrastructure.mcp_client_pool.read_json", return_value=config
        ):
            with patch.dict(os.environ, {"VAR": "val"}):
                result = _load_server_config("srv")
                assert result["env"]["NUM"] == 42
                assert result["env"]["STR"] == "val"


class TestGetClient:
    def test_throws_for_unknown_server(self):
        with pytest.raises(McpConnectionError):
            asyncio.run(get_client("nonexistent-server-12345"))

    def test_creates_and_caches_client(self):
        mock_client = MagicMock()
        mock_client.connected = True
        mock_client.connect = AsyncMock()
        mock_client.list_tools.return_value = ["tool1", "tool2"]
        mock_client.protocol_version = "2025-11-25"

        server_cfg = {"command": "echo"}
        with (
            patch(
                "mcp_server.infrastructure.mcp_client_pool._load_server_config",
                return_value=server_cfg,
            ),
            patch(
                "mcp_server.infrastructure.mcp_client_pool.MCPClient",
                return_value=mock_client,
            ),
        ):
            # Clear pool
            mcp_client_pool._pool.clear()

            result = asyncio.run(get_client("test-srv"))
            assert result is mock_client
            mock_client.connect.assert_awaited_once()

            # Second call should return cached
            result2 = asyncio.run(get_client("test-srv"))
            assert result2 is mock_client
            # connect should still only have been called once
            assert mock_client.connect.await_count == 1

        mcp_client_pool._pool.clear()

    def test_replaces_stale_disconnected_client(self):
        stale_client = MagicMock()
        stale_client.connected = False
        stale_client.close = MagicMock()

        new_client = MagicMock()
        new_client.connected = True
        new_client.connect = AsyncMock()
        new_client.list_tools.return_value = []
        new_client.protocol_version = "2025-11-25"

        mcp_client_pool._pool.clear()
        mcp_client_pool._pool["stale-srv"] = stale_client

        server_cfg = {"command": "echo"}
        with (
            patch(
                "mcp_server.infrastructure.mcp_client_pool._load_server_config",
                return_value=server_cfg,
            ),
            patch(
                "mcp_server.infrastructure.mcp_client_pool.MCPClient",
                return_value=new_client,
            ),
        ):
            result = asyncio.run(get_client("stale-srv"))
            assert result is new_client
            stale_client.close.assert_called_once()

        mcp_client_pool._pool.clear()


class TestCloseClient:
    def test_safe_for_nonexistent(self):
        close_client("never-connected")

    def test_closes_existing_client(self):
        mock_client = MagicMock()
        mcp_client_pool._pool["to-close"] = mock_client
        close_client("to-close")
        mock_client.close.assert_called_once()
        assert "to-close" not in mcp_client_pool._pool

    def test_removes_from_pool(self):
        mock_client = MagicMock()
        mcp_client_pool._pool["rm-test"] = mock_client
        close_client("rm-test")
        assert "rm-test" not in mcp_client_pool._pool


class TestCloseAll:
    def test_safe_when_empty(self):
        mcp_client_pool._pool.clear()
        close_all()

    def test_can_call_multiple_times(self):
        close_all()
        close_all()

    def test_closes_all_clients(self):
        c1 = MagicMock()
        c2 = MagicMock()
        mcp_client_pool._pool.clear()
        mcp_client_pool._pool["a"] = c1
        mcp_client_pool._pool["b"] = c2
        close_all()
        c1.close.assert_called_once()
        c2.close.assert_called_once()
        assert len(mcp_client_pool._pool) == 0
