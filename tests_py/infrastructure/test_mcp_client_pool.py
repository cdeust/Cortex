"""Tests for mcp_server.infrastructure.mcp_client_pool — ported from
mcp-client-pool.test.js."""

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


def _fake_client(busy: bool = False, connected: bool = True) -> MagicMock:
    """A pooled-client stand-in. ``busy`` drives LRU eviction safety;
    ``connected`` drives the stale-replacement path. ``close`` is a plain
    Mock so eviction can be asserted."""
    c = MagicMock()
    c.busy = busy
    c.connected = connected
    c.close = MagicMock()
    return c


class TestPoolBounding:
    """Phase-3 bounded-io: max-connections + LRU eviction + fail-fast.

    NOTE: no asyncio.sleep is mocked anywhere here — a mocked sleep turns
    MCPClient._idle_loop into an infinite busy-spin that hangs the suite
    (memory: ci_311_idle_loop_busyspin). These tests use plain fake clients
    and never spawn a real MCPClient/idle loop.
    """

    def _patch_max(self, n: int):
        """Force the resolved pool cap to ``n`` regardless of host cpu_count."""
        settings = MagicMock()
        settings.mcp_pool_max_connections = n
        return patch(
            "mcp_server.infrastructure.mcp_client_pool.get_memory_settings",
            return_value=settings,
        )

    def _patch_new_client(self, client):
        return (
            patch(
                "mcp_server.infrastructure.mcp_client_pool._load_server_config",
                return_value={"command": "echo"},
            ),
            patch(
                "mcp_server.infrastructure.mcp_client_pool.MCPClient",
                return_value=client,
            ),
        )

    def test_pool_never_exceeds_max_and_evicts_lru_idle(self):
        mcp_client_pool._pool.clear()
        # Fill the pool to capacity (max=2) with two idle connections.
        first = _fake_client(busy=False)
        second = _fake_client(busy=False)
        mcp_client_pool._pool["first"] = first
        mcp_client_pool._pool["second"] = second

        new_client = _fake_client(busy=False)
        new_client.connect = AsyncMock()
        new_client.list_tools.return_value = []
        new_client.protocol_version = "v"

        cfg_patch, mcpcls_patch = self._patch_new_client(new_client)
        with self._patch_max(2), cfg_patch, mcpcls_patch:
            result = asyncio.run(get_client("third"))

        # Pool stayed at the cap; LRU ("first") was evicted, not "second".
        assert result is new_client
        assert len(mcp_client_pool._pool) == 2
        assert "first" not in mcp_client_pool._pool
        assert "second" in mcp_client_pool._pool
        assert "third" in mcp_client_pool._pool
        first.close.assert_called_once()
        second.close.assert_not_called()
        mcp_client_pool._pool.clear()

    def test_lru_touch_protects_recently_used_from_eviction(self):
        mcp_client_pool._pool.clear()
        older = _fake_client(busy=False)
        newer = _fake_client(busy=False)
        mcp_client_pool._pool["older"] = older
        mcp_client_pool._pool["newer"] = newer

        # Touch "older" via a cache hit → it becomes most-recently-used,
        # so the NEXT admission must evict "newer" instead.
        with self._patch_max(2):
            hit = asyncio.run(get_client("older"))
        assert hit is older

        new_client = _fake_client(busy=False)
        new_client.connect = AsyncMock()
        new_client.list_tools.return_value = []
        new_client.protocol_version = "v"
        cfg_patch, mcpcls_patch = self._patch_new_client(new_client)
        with self._patch_max(2), cfg_patch, mcpcls_patch:
            asyncio.run(get_client("third"))

        assert "newer" not in mcp_client_pool._pool
        assert "older" in mcp_client_pool._pool
        newer.close.assert_called_once()
        older.close.assert_not_called()
        mcp_client_pool._pool.clear()

    def test_fail_fast_when_all_connections_busy(self):
        mcp_client_pool._pool.clear()
        # Pool full and every connection is serving an in-flight call.
        busy_a = _fake_client(busy=True)
        busy_b = _fake_client(busy=True)
        mcp_client_pool._pool["a"] = busy_a
        mcp_client_pool._pool["b"] = busy_b

        with self._patch_max(2):
            with pytest.raises(McpConnectionError, match="pool exhausted"):
                asyncio.run(get_client("c"))

        # No eviction, no growth — the busy connections are untouched.
        assert len(mcp_client_pool._pool) == 2
        busy_a.close.assert_not_called()
        busy_b.close.assert_not_called()
        mcp_client_pool._pool.clear()

    def test_busy_connection_is_skipped_idle_one_evicted(self):
        mcp_client_pool._pool.clear()
        # LRU is busy; the next-oldest is idle → idle one must be evicted.
        busy_lru = _fake_client(busy=True)
        idle_next = _fake_client(busy=False)
        mcp_client_pool._pool["busy_lru"] = busy_lru
        mcp_client_pool._pool["idle_next"] = idle_next

        new_client = _fake_client(busy=False)
        new_client.connect = AsyncMock()
        new_client.list_tools.return_value = []
        new_client.protocol_version = "v"
        cfg_patch, mcpcls_patch = self._patch_new_client(new_client)
        with self._patch_max(2), cfg_patch, mcpcls_patch:
            asyncio.run(get_client("fresh"))

        assert "busy_lru" in mcp_client_pool._pool
        assert "idle_next" not in mcp_client_pool._pool
        busy_lru.close.assert_not_called()
        idle_next.close.assert_called_once()
        mcp_client_pool._pool.clear()


class TestPerServerConcurrencyCap:
    """Per-server concurrency cap (deliverable 2). The cap is enforced by
    upstream_governor.govern, keyed by server name. Verify a cap of 1
    serialises concurrent callers using an order-recording fake transport.
    """

    def test_semaphore_serialises_when_cap_is_one(self):
        from mcp_server.infrastructure import upstream_governor

        upstream_governor.reset()
        order: list[str] = []
        live = {"n": 0}

        async def worker(tag: str) -> None:
            # Cap=1 → at most one worker may be inside the critical section.
            async with upstream_governor.govern("srv", max_concurrent=1):
                live["n"] += 1
                # If serialisation holds, this assertion never sees 2.
                assert live["n"] == 1, f"{tag} saw {live['n']} concurrent holders"
                order.append(f"{tag}:enter")
                # Yield control so a second worker WOULD interleave here if
                # the cap were not enforced. No sleep mock — a real 0-delay
                # yield via asyncio.sleep(0) (never mock sleep: idle-loop spin).
                await asyncio.sleep(0)
                order.append(f"{tag}:exit")
                live["n"] -= 1

        async def run() -> None:
            await asyncio.wait_for(asyncio.gather(worker("A"), worker("B")), timeout=5)

        asyncio.run(run())
        upstream_governor.reset()

        # With cap=1, each worker's enter/exit are adjacent (no interleave).
        assert order in (
            ["A:enter", "A:exit", "B:enter", "B:exit"],
            ["B:enter", "B:exit", "A:enter", "A:exit"],
        )

    def test_cap_greater_than_one_allows_overlap(self):
        from mcp_server.infrastructure import upstream_governor

        upstream_governor.reset()
        # Two permits → both workers must be able to hold the permit
        # simultaneously. ``both_inside`` is an asyncio.Event that only
        # the SECOND entrant sets after counting two concurrent holders;
        # each worker waits on it inside its critical section. If the cap
        # were 1, the first worker would block forever on this event
        # (the second can't enter to set it) and gather would deadlock —
        # so passing proves genuine overlap, not interleave luck.
        order: list[str] = []

        async def run() -> None:
            both_inside = asyncio.Event()
            inside = {"n": 0}

            async def worker(tag: str) -> None:
                async with upstream_governor.govern("srv2", max_concurrent=2):
                    order.append(f"{tag}:enter")
                    inside["n"] += 1
                    if inside["n"] == 2:
                        both_inside.set()
                    await both_inside.wait()
                    order.append(f"{tag}:exit")

            await asyncio.wait_for(asyncio.gather(worker("A"), worker("B")), timeout=5)

        asyncio.run(run())
        upstream_governor.reset()

        # cap=2 → both entered before either exited (true overlap).
        assert order[0].endswith(":enter")
        assert order[1].endswith(":enter")
        assert sorted(order) == ["A:enter", "A:exit", "B:enter", "B:exit"]


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
