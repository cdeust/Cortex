"""Tests for mcp_server.infrastructure.mcp_client — comprehensive coverage."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.mcp_client import (
    MCPClient,
    CLIENT_INFO,
    PROTOCOL_VERSION,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_client(**overrides) -> tuple:
    config = {"command": "echo", "args": [], **overrides}
    client = MCPClient(config)
    # Allow test commands through the security allowlist
    client._extra_allowed_commands = {"echo", "mybin"}
    return config, client


def _mock_proc(stdout_lines: list[bytes] | None = None):
    """Build a mock subprocess with stdin/stdout/stderr."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.terminate = MagicMock()

    if stdout_lines is not None:
        remaining = list(stdout_lines)

        async def _readline():
            if remaining:
                return remaining.pop(0)
            return b""

        proc.stdout = MagicMock()
        proc.stdout.readline = _readline
    else:
        proc.stdout = MagicMock()
        proc.stdout.readline = AsyncMock(return_value=b"")

    proc.stderr = MagicMock()
    proc.stderr.readline = AsyncMock(return_value=b"")

    return proc


# ── Constructor ──────────────────────────────────────────────────────────────


class TestMCPClientConstructor:
    def test_default_timeouts(self):
        _, client = _make_client()
        assert client._connect_timeout_ms == 10000
        assert client._call_timeout_ms == 120000
        assert client._idle_timeout_ms == 300000

    def test_custom_timeouts(self):
        _, client = _make_client(
            connectTimeoutMs=5000, callTimeoutMs=60000, idleTimeoutMs=120000
        )
        assert client._connect_timeout_ms == 5000
        assert client._call_timeout_ms == 60000
        assert client._idle_timeout_ms == 120000

    def test_starts_with_zero_tool_calls(self):
        _, client = _make_client()
        assert client.tool_calls == 0

    def test_starts_not_connected(self):
        _, client = _make_client()
        assert client.connected is False

    def test_initial_state(self):
        _, client = _make_client()
        assert client._buffer == ""
        assert client._proc is None
        assert client._tools == {}
        assert client._server_info is None
        assert client._negotiated_version is None
        assert client._idle_task is None
        assert client._reader_task is None
        assert client._req_id == 0
        assert client._pending == {}

    def test_falsy_timeout_uses_default(self):
        _, client = _make_client(connectTimeoutMs=0)
        assert client._connect_timeout_ms == 10000


# ── Properties ───────────────────────────────────────────────────────────────


class TestMCPClientProperties:
    def test_server_info_none_initially(self):
        _, client = _make_client()
        assert client.server_info is None

    def test_protocol_version_none_initially(self):
        _, client = _make_client()
        assert client.protocol_version is None

    def test_connected_false_initially(self):
        _, client = _make_client()
        assert client.connected is False


# ── list_tools ───────────────────────────────────────────────────────────────


class TestMCPClientListTools:
    def test_empty_before_connect(self):
        _, client = _make_client()
        assert client.list_tools() == {}

    def test_returns_copy(self):
        _, client = _make_client()
        client._tools = {"foo": {"name": "foo"}}
        result = client.list_tools()
        assert result == {"foo": {"name": "foo"}}
        result["bar"] = {"name": "bar"}
        assert "bar" not in client._tools


# ── _notify ──────────────────────────────────────────────────────────────────


class TestMCPClientNotify:
    def test_sends_without_id(self):
        _, client = _make_client()
        proc = _mock_proc()
        client._proc = proc
        client._notify("notifications/initialized")

        data = proc.stdin.write.call_args[0][0]
        sent = json.loads(data.decode().strip())
        assert sent["jsonrpc"] == "2.0"
        assert sent["method"] == "notifications/initialized"
        assert "id" not in sent

    def test_sends_with_params(self):
        _, client = _make_client()
        proc = _mock_proc()
        client._proc = proc
        client._notify("test/method", {"key": "value"})

        data = proc.stdin.write.call_args[0][0]
        sent = json.loads(data.decode().strip())
        assert sent["params"] == {"key": "value"}

    def test_sends_without_params_key_when_none(self):
        _, client = _make_client()
        proc = _mock_proc()
        client._proc = proc
        client._notify("test/method")

        data = proc.stdin.write.call_args[0][0]
        sent = json.loads(data.decode().strip())
        assert "params" not in sent


# ── connect ──────────────────────────────────────────────────────────────────


class TestMCPClientConnect:
    def test_connect_noop_when_already_connected(self):
        _, client = _make_client()
        client._connected = True
        _run(client.connect())
        assert client._proc is None

    def test_connect_spawn_failure_raises(self):
        _, client = _make_client()
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("not found"),
        ):
            with pytest.raises(McpConnectionError, match="Failed to spawn"):
                _run(client.connect())

    def test_connect_handshake_success(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()

            init_response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "protocolVersion": "2025-11-25",
                            "serverInfo": {"name": "test-server"},
                        },
                    }
                ).encode()
                + b"\n"
            )

            tools_response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {
                            "tools": [{"name": "my_tool", "description": "A tool"}]
                        },
                    }
                ).encode()
                + b"\n"
            )

            # Simulate real pipe: responses only available after requests are sent.
            # _read_loop runs concurrently; it must not consume responses before
            # _send() registers the corresponding future in _pending.
            drain_event = asyncio.Event()
            responses = [init_response, tools_response]
            resp_idx = 0

            async def _readline():
                nonlocal resp_idx
                if resp_idx < len(responses):
                    # Wait until a request has been written (drain called)
                    await drain_event.wait()
                    drain_event.clear()
                    line = responses[resp_idx]
                    resp_idx += 1
                    return line
                return b""

            async def _drain():
                # Signal that a request was written, so readline can proceed
                drain_event.set()

            proc.stdout.readline = _readline
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.stdin.drain = _drain

            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await client.connect()

            assert client.connected is True
            assert client.protocol_version == "2025-11-25"
            assert client.server_info == {"name": "test-server"}
            assert "my_tool" in client.list_tools()
            client.close()

        _run(_test())

    def test_connect_handshake_defaults_missing_fields(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()

            init_response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {},
                    }
                ).encode()
                + b"\n"
            )

            tools_response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {},
                    }
                ).encode()
                + b"\n"
            )

            drain_event = asyncio.Event()
            responses = [init_response, tools_response]
            resp_idx = 0

            async def _readline():
                nonlocal resp_idx
                if resp_idx < len(responses):
                    await drain_event.wait()
                    drain_event.clear()
                    line = responses[resp_idx]
                    resp_idx += 1
                    return line
                return b""

            async def _drain():
                drain_event.set()

            proc.stdout.readline = _readline
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.stdin.drain = _drain

            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await client.connect()

            assert client.connected is True
            assert client.protocol_version == PROTOCOL_VERSION
            assert client.server_info == {}
            assert client.list_tools() == {}
            client.close()

        _run(_test())

    def test_connect_handshake_failure_closes_and_raises(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()

            error_response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32600, "message": "Bad request"},
                    }
                ).encode()
                + b"\n"
            )

            drain_event = asyncio.Event()
            responses = [error_response]
            resp_idx = 0

            async def _readline():
                nonlocal resp_idx
                if resp_idx < len(responses):
                    await drain_event.wait()
                    drain_event.clear()
                    line = responses[resp_idx]
                    resp_idx += 1
                    return line
                return b""

            async def _drain():
                drain_event.set()

            proc.stdout.readline = _readline
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.stdin.drain = _drain

            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(McpConnectionError, match="Handshake failed"):
                        await client.connect()

            assert client.connected is False

        _run(_test())

    def test_connect_uses_config_env_and_cwd(self):
        async def _test():
            _, client = _make_client(
                command="mybin", args=["--flag"], cwd="/tmp", env={"FOO": "bar"}
            )
            proc = _mock_proc()

            init_resp = (
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode() + b"\n"
            )
            tools_resp = (
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {}}).encode() + b"\n"
            )

            drain_event = asyncio.Event()
            responses = [init_resp, tools_resp]
            resp_idx = 0

            async def _readline():
                nonlocal resp_idx
                if resp_idx < len(responses):
                    await drain_event.wait()
                    drain_event.clear()
                    line = responses[resp_idx]
                    resp_idx += 1
                    return line
                return b""

            async def _drain():
                drain_event.set()

            proc.stdout.readline = _readline
            proc.stderr.readline = AsyncMock(return_value=b"")
            proc.stdin.drain = _drain

            with patch(
                "asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=proc,
            ) as mock_exec:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await client.connect()

            call_kwargs = mock_exec.call_args
            assert call_kwargs[1]["cwd"] == "/tmp"
            assert "FOO" in call_kwargs[1]["env"]
            assert call_kwargs[1]["env"]["FOO"] == "bar"
            client.close()

        _run(_test())


# ── call ─────────────────────────────────────────────────────────────────────


class TestMCPClientCall:
    def test_call_not_connected_raises(self):
        _, client = _make_client()
        with pytest.raises(McpConnectionError, match="Not connected"):
            _run(client.call("some_tool"))

    def test_call_returns_structured_content(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            expected = {"data": "hello"}
            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"structuredContent": expected},
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            result = await client.call("my_tool", {"arg": "val"})
            assert result == expected
            assert client.tool_calls == 1

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_returns_text_content_as_json(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "content": [{"type": "text", "text": '{"key": "value"}'}]
                        },
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            result = await client.call("my_tool")
            assert result == {"key": "value"}

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_returns_text_as_string_on_json_error(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {
                            "content": [{"type": "text", "text": "plain text result"}]
                        },
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            result = await client.call("my_tool")
            assert result == "plain text result"

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_returns_none_when_no_content(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {},
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            result = await client.call("my_tool")
            assert result is None

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_returns_none_on_null_result(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": None,
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            result = await client.call("my_tool")
            assert result is None

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_returns_full_result_when_no_text_block(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"content": [{"type": "image", "data": "abc"}]},
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            result = await client.call("my_tool")
            assert result == {"content": [{"type": "image", "data": "abc"}]}

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_error_response_raises(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32000, "message": "Tool failed"},
                    }
                ).encode()
                + b"\n"
            )

            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            client._reader_task = asyncio.create_task(client._read_loop())

            with pytest.raises(McpConnectionError, match="Tool failed"):
                await client.call("my_tool")

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())

    def test_call_increments_tool_calls(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            resp1 = (
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode() + b"\n"
            )
            resp2 = (
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": {}}).encode() + b"\n"
            )

            # Simulate real pipe: responses appear only after requests are written
            drain_event = asyncio.Event()
            responses = [resp1, resp2]
            resp_idx = 0

            async def _readline():
                nonlocal resp_idx
                if resp_idx < len(responses):
                    await drain_event.wait()
                    drain_event.clear()
                    line = responses[resp_idx]
                    resp_idx += 1
                    return line
                return b""

            async def _drain():
                drain_event.set()

            proc.stdout.readline = _readline
            proc.stdin.drain = _drain
            client._reader_task = asyncio.create_task(client._read_loop())

            await client.call("tool1")
            await client.call("tool2")
            assert client.tool_calls == 2

            client._reader_task.cancel()
            try:
                await client._reader_task
            except asyncio.CancelledError:
                pass

        _run(_test())


# ── close ────────────────────────────────────────────────────────────────────


class TestMCPClientClose:
    def test_safe_when_not_connected(self):
        _, client = _make_client()
        client.close()
        assert client.connected is False

    def test_cancels_tasks_and_clears_proc(self):
        _, client = _make_client()
        client._connected = True
        proc = _mock_proc()
        client._proc = proc

        idle_task = MagicMock()
        reader_task = MagicMock()
        client._idle_task = idle_task
        client._reader_task = reader_task

        client.close()

        assert client.connected is False
        idle_task.cancel.assert_called_once()
        reader_task.cancel.assert_called_once()
        assert client._idle_task is None
        assert client._reader_task is None
        assert client._proc is None

    def test_rejects_pending_futures(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future1 = loop.create_future()
            future2 = loop.create_future()
            client._pending = {1: future1, 2: future2}

            client.close()

            assert future1.done()
            assert future2.done()
            with pytest.raises(McpConnectionError, match="Client closed"):
                future1.result()
            assert client._pending == {}

        _run(_test())

    def test_close_handles_stdin_close_error(self):
        _, client = _make_client()
        client._connected = True
        proc = _mock_proc()
        proc.stdin.close = MagicMock(side_effect=OSError("broken pipe"))
        client._proc = proc

        client.close()
        assert client._proc is None

    def test_close_handles_terminate_error(self):
        _, client = _make_client()
        client._connected = True
        proc = _mock_proc()
        proc.terminate = MagicMock(side_effect=ProcessLookupError("already dead"))
        client._proc = proc

        client.close()
        assert client._proc is None

    def test_does_not_reject_already_done_futures(self):
        async def _test():
            _, client = _make_client()
            client._connected = True
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            done_future = loop.create_future()
            done_future.set_result("already done")
            client._pending = {1: done_future}

            client.close()
            assert done_future.result() == "already done"

        _run(_test())


# ── _read_loop ───────────────────────────────────────────────────────────────


class TestMCPClientReadLoop:
    def test_resolves_pending_futures(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            client._pending[42] = future

            response = (
                json.dumps(
                    {"jsonrpc": "2.0", "id": 42, "result": {"ok": True}}
                ).encode()
                + b"\n"
            )
            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()

            assert future.done()
            assert future.result() == {"ok": True}
            assert 42 not in client._pending

        _run(_test())

    def test_sets_error_on_error_response(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            client._pending[1] = future

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -1, "message": "oops"},
                    }
                ).encode()
                + b"\n"
            )
            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()

            assert future.done()
            with pytest.raises(McpConnectionError, match="oops"):
                future.result()

        _run(_test())

    def test_skips_empty_and_content_length_lines(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            client._pending[1] = future

            lines = [
                b"\n",
                b"Content-Length: 42\n",
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": "ok"}).encode()
                + b"\n",
                b"",
            ]
            remaining = list(lines)

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()

            assert future.result() == "ok"

        _run(_test())

    def test_ignores_invalid_json(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            client._pending[1] = future

            lines = [
                b"not-valid-json\n",
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": "ok"}).encode()
                + b"\n",
                b"",
            ]
            remaining = list(lines)

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()
            assert future.result() == "ok"

        _run(_test())

    def test_ignores_messages_without_matching_id(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            client._pending[2] = future

            lines = [
                json.dumps({"jsonrpc": "2.0", "method": "notification"}).encode()
                + b"\n",
                json.dumps({"jsonrpc": "2.0", "id": 999, "result": "wrong"}).encode()
                + b"\n",
                json.dumps({"jsonrpc": "2.0", "id": 2, "result": "right"}).encode()
                + b"\n",
                b"",
            ]
            remaining = list(lines)

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()
            assert future.result() == "right"

        _run(_test())

    def test_skips_done_future(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            future.set_result("already done")
            client._pending[1] = future

            response = (
                json.dumps({"jsonrpc": "2.0", "id": 1, "result": "late"}).encode()
                + b"\n"
            )
            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()
            assert future.result() == "already done"

        _run(_test())

    def test_handles_error_without_message(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            client._pending[1] = future

            response = (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -1},
                    }
                ).encode()
                + b"\n"
            )
            remaining = [response, b""]

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stdout.readline = _readline
            await client._read_loop()

            with pytest.raises(McpConnectionError, match="Unknown error"):
                future.result()

        _run(_test())


# ── _send ────────────────────────────────────────────────────────────────────


class TestMCPClientSend:
    def test_send_writes_jsonrpc_message(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            async def _resolve():
                await asyncio.sleep(0.01)
                future = client._pending.get(1)
                if future and not future.done():
                    future.set_result({"ok": True})

            asyncio.create_task(_resolve())

            result = await client._send("test/method", {"arg": 1})
            assert result == {"ok": True}

            data = proc.stdin.write.call_args[0][0]
            sent = json.loads(data.decode().strip())
            assert sent["jsonrpc"] == "2.0"
            assert sent["id"] == 1
            assert sent["method"] == "test/method"
            assert sent["params"] == {"arg": 1}

        _run(_test())

    def test_send_increments_req_id(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            # Resolve each pending future after drain is called
            async def _resolver():
                for rid in [1, 2]:
                    # Poll until the future is registered
                    while rid not in client._pending:
                        await asyncio.sleep(0)
                    f = client._pending[rid]
                    if not f.done():
                        f.set_result(None)

            asyncio.create_task(_resolver())

            await client._send("m1", {})
            await client._send("m2", {})
            assert client._req_id == 2

        _run(_test())


# ── _touch_activity ──────────────────────────────────────────────────────────


class TestTouchActivity:
    def test_touch_activity_handles_no_event_loop(self):
        _, client = _make_client()
        with patch("asyncio.get_event_loop", side_effect=RuntimeError("no loop")):
            client._touch_activity()  # should not raise


# ── _stderr_loop ─────────────────────────────────────────────────────────────


class TestStderrLoop:
    def test_stderr_loop_prints_and_exits(self):
        async def _test():
            _, client = _make_client()
            proc = _mock_proc()
            client._proc = proc

            lines = [b"some error\n", b""]
            remaining = list(lines)

            async def _readline():
                return remaining.pop(0) if remaining else b""

            proc.stderr.readline = _readline
            await client._stderr_loop()

        _run(_test())


# ── _idle_loop ───────────────────────────────────────────────────────────────


class TestIdleLoop:
    def test_idle_loop_closes_when_idle(self):
        async def _test():
            _, client = _make_client(idleTimeoutMs=100)
            client._connected = True
            # Set last_activity far in the past relative to loop clock
            loop = asyncio.get_running_loop()
            client._last_activity = loop.time() - 999
            proc = _mock_proc()
            client._proc = proc

            call_count = 0

            async def _fast_sleep(t):
                nonlocal call_count
                call_count += 1
                if call_count > 2:
                    raise asyncio.CancelledError

            with patch("asyncio.sleep", side_effect=_fast_sleep):
                await client._idle_loop()

            assert client.connected is False

        _run(_test())

    def test_idle_loop_cancellation(self):
        async def _test():
            _, client = _make_client(idleTimeoutMs=999999000)
            client._connected = True
            client._last_activity = asyncio.get_running_loop().time()

            async def _cancel_sleep(t):
                raise asyncio.CancelledError

            with patch("asyncio.sleep", side_effect=_cancel_sleep):
                await client._idle_loop()

            assert client.connected is True

        _run(_test())


# ── Module constants ─────────────────────────────────────────────────────────


class TestModuleConstants:
    def test_client_info(self):
        assert CLIENT_INFO == {"name": "cortex", "version": "1.0.0"}

    def test_protocol_version(self):
        assert PROTOCOL_VERSION == "2025-11-25"
