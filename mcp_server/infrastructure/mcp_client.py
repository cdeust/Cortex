"""Generic MCP client over stdio — spawns a child process, performs
JSON-RPC 2.0 handshake, calls tools.

Implements MCP 2025-11-25 handshake with version negotiation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from mcp_server.errors import McpConnectionError

CLIENT_INFO = {"name": "cortex", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-11-25"


class MCPClient:
    def __init__(self, config: dict):
        self._config = config
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._buffer = ""
        self._proc: asyncio.subprocess.Process | None = None
        self._tools: dict[str, Any] = {}
        self._server_info: dict | None = None
        self._negotiated_version: str | None = None
        self._connected = False
        self._connect_timeout_ms = config.get("connectTimeoutMs") or 10000
        # callTimeoutMs: positive int = ms, 0 or None = no per-call timeout
        # (used for long-running upstream indexing).
        raw_call_timeout = config.get("callTimeoutMs")
        if raw_call_timeout is None:
            self._call_timeout_ms: int | None = 120000
        elif raw_call_timeout == 0:
            self._call_timeout_ms = None
        else:
            self._call_timeout_ms = int(raw_call_timeout)
        self._idle_timeout_ms = config.get("idleTimeoutMs") or 300000
        self._last_activity = 0.0
        self._idle_task: asyncio.Task | None = None
        self._reader_task: asyncio.Task | None = None
        self.tool_calls = 0

    async def connect(self) -> None:
        """Spawn child process, perform MCP handshake, and list tools."""
        if self._connected:
            return

        await self._spawn_process()
        self._reader_task = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._stderr_loop())
        await asyncio.sleep(1.5)
        await self._perform_handshake()

    # Allowlisted MCP server commands. Only these binaries may be spawned.
    # Config-supplied commands are validated against this list to prevent
    # command injection (CodeQL py/command-line-injection, CWE-78).
    _ALLOWED_COMMANDS = frozenset(
        {
            "node",
            "npx",
            "python",
            "python3",
            "uvx",
            "uv",
            "cortex",
            "mcp-server",
        }
    )

    async def _spawn_process(self) -> None:
        """Spawn the child MCP server process.

        Security: command must be in _ALLOWED_COMMANDS allowlist.
        Args are passed as a list (no shell=True). Environment is
        merged from os.environ + config, not constructed from user input.
        """
        import os
        import shutil

        raw_command: str = self._config["command"]
        args = self._config.get("args") or []
        cwd = self._config.get("cwd")
        env = self._config.get("env")
        merged_env = {**os.environ, **(env or {})}
        line_limit = 10 * 1024 * 1024

        # Validate command against allowlist (CWE-78 mitigation).
        # In test/dev, extra commands can be allowed via _extra_allowed_commands.
        allowed = self._ALLOWED_COMMANDS | getattr(
            self, "_extra_allowed_commands", set()
        )
        base_cmd = raw_command.split("/")[-1] if "/" in raw_command else raw_command
        if base_cmd not in allowed:
            raise McpConnectionError(
                f"Command '{raw_command}' not in allowed list: {sorted(allowed)}"
            )
        # Resolve to full path via shutil.which to avoid PATH manipulation
        command = shutil.which(raw_command) or raw_command

        try:
            self._proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    command,
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=merged_env,
                    limit=line_limit,
                ),
                timeout=self._connect_timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            raise McpConnectionError(
                f"Connect timeout after {self._connect_timeout_ms}ms",
                {"command": command, "args": args},
            )
        except Exception as e:
            raise McpConnectionError(
                f"Failed to spawn: {e}",
                {"command": command, "args": args},
            )

    async def _perform_handshake(self) -> None:
        """Initialize protocol, negotiate version, and discover tools."""
        command = self._config["command"]
        try:
            init_result = await self._send(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            )

            self._negotiated_version = (
                init_result.get("protocolVersion") or PROTOCOL_VERSION
            )
            self._server_info = init_result.get("serverInfo") or {}

            self._notify("notifications/initialized")

            list_result = await self._send("tools/list", {})
            for tool in list_result.get("tools") or []:
                self._tools[tool["name"]] = tool

            self._connected = True
            self._touch_activity()
            self._idle_task = asyncio.create_task(self._idle_loop())

        except Exception as e:
            self.close()
            raise McpConnectionError(
                f"Handshake failed: {e}",
                {"command": command},
            )

    async def call(self, name: str, args: dict | None = None) -> Any:
        """Call a tool on the remote MCP server."""
        if not self._connected:
            raise McpConnectionError("Not connected — call connect() first")

        self.tool_calls += 1
        self._touch_activity()

        result = await self._send("tools/call", {"name": name, "arguments": args or {}})

        # Prefer structuredContent (MCP 2025-11-25)
        if result and result.get("structuredContent"):
            return result["structuredContent"]

        if not result or not result.get("content"):
            return None

        for block in result["content"]:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (json.JSONDecodeError, ValueError):
                    return block["text"]

        return result

    def list_tools(self) -> dict[str, Any]:
        return dict(self._tools)

    @property
    def server_info(self) -> dict | None:
        return self._server_info

    @property
    def protocol_version(self) -> str | None:
        return self._negotiated_version

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def idle(self) -> bool:
        loop = asyncio.get_running_loop()
        return (loop.time() - self._last_activity) > (self._idle_timeout_ms / 1000)

    def close(self) -> None:
        """Gracefully close the connection."""
        self._connected = False

        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None

        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

        # Reject pending requests
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpConnectionError("Client closed"))
        self._pending.clear()

        if self._proc:
            try:
                self._proc.stdin.close()  # type: ignore
            except Exception:
                pass
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    # ── Private ──────────────────────────────────────────────────────────────

    async def _send(self, method: str, params: dict) -> Any:
        self._req_id += 1
        req_id = self._req_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        msg = json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        self._proc.stdin.write((msg + "\n").encode())  # type: ignore
        await self._proc.stdin.drain()  # type: ignore

        if self._call_timeout_ms is None:
            return await future
        try:
            return await asyncio.wait_for(future, timeout=self._call_timeout_ms / 1000)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise McpConnectionError(
                f"Timeout after {self._call_timeout_ms}ms: {method}"
            )

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())  # type: ignore

    def _touch_activity(self) -> None:
        try:
            self._last_activity = asyncio.get_running_loop().time()
        except Exception:
            pass

    async def _read_loop(self) -> None:
        try:
            while True:
                line = await self._proc.stdout.readline()  # type: ignore
                if not line:
                    break
                decoded = line.decode("utf-8").strip()
                if not decoded or decoded.startswith("Content-Length"):
                    continue
                try:
                    msg = json.loads(decoded)
                    msg_id = msg.get("id")
                    if msg_id is not None and msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if not future.done():
                            if msg.get("error"):
                                future.set_exception(
                                    McpConnectionError(
                                        msg["error"].get("message", "Unknown error")
                                    )
                                )
                            else:
                                future.set_result(msg.get("result"))
                except (json.JSONDecodeError, ValueError):
                    pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _stderr_loop(self) -> None:
        log_fh = self._open_stderr_log()
        try:
            while True:
                line = await self._proc.stderr.readline()  # type: ignore
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                print(
                    f"[mcp-client] {self._config['command']}: {decoded}",
                    file=sys.stderr,
                )
                if log_fh is not None:
                    try:
                        log_fh.write(decoded + "\n")
                        log_fh.flush()
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            if log_fh is not None:
                try:
                    log_fh.close()
                except Exception:
                    pass

    def _open_stderr_log(self):
        """Open a per-server stderr log file under ~/.cache/cortex/mcp-logs/.

        Persists upstream MCP stderr (e.g. ai-architect-mcp indexer progress)
        for post-hoc investigation. Returns None on any error — logging
        failure must not break the connection.
        """
        import os
        import pathlib

        try:
            base = pathlib.Path.home() / ".cache" / "cortex" / "mcp-logs"
            base.mkdir(parents=True, exist_ok=True)
            raw = self._config.get("command") or "unknown"
            stem = raw.split("/")[-1] or "unknown"
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
            pid = os.getpid()
            return open(base / f"{safe}.{pid}.log", "a", encoding="utf-8")
        except Exception:
            return None

    async def _idle_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                if self.idle:
                    print(
                        "[mcp-client] Idle timeout — closing connection",
                        file=sys.stderr,
                    )
                    self.close()
                    break
        except asyncio.CancelledError:
            pass
