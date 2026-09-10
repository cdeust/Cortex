"""Generic MCP client over stdio — spawns a child process, performs
JSON-RPC 2.0 handshake, calls tools.

Implements MCP 2025-11-25 handshake with version negotiation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

from mcp_server.infrastructure.upstream_identity import ALLOWED_UPSTREAM_COMMANDS
from typing import Any, NoReturn

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.mcp_call_timeout import default_call_timeout_s
import os
import shutil
import pathlib

logger = logging.getLogger(__name__)

CLIENT_INFO = {"name": "cortex", "version": "1.0.0"}
PROTOCOL_VERSION = "2025-11-25"


def _resolve_call_timeout_ms(raw: Any) -> int | None:
    """Map the config's ``callTimeoutMs`` to the client's per-call cap.

    source: ADR-0532"""
    if raw is None:
        return 120000
    value = int(raw)
    return None if value == 0 else value


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
        # source: ADR-0532
        self._extra_allowed_commands: set[str] = set()
        self._connect_timeout_ms = config.get("connectTimeoutMs") or 10000
        self._call_timeout_ms = _resolve_call_timeout_ms(config.get("callTimeoutMs"))
        self._idle_timeout_ms = config.get("idleTimeoutMs") or 300000
        self._init_liveness_state()
        self.tool_calls = 0

    def _init_liveness_state(self) -> None:
        """Liveness + loop-binding state (split from __init__, same fields)."""
        self._last_activity = 0.0
        # source: ADR-0532
        self._last_child_output = time.monotonic()
        self._idle_task: asyncio.Task | None = None
        self._reader_task: asyncio.Task | None = None
        # source: ADR-0532
        self._bound_loop: asyncio.AbstractEventLoop | None = None

    async def connect(self) -> None:
        """Spawn child process, perform MCP handshake, and list tools."""
        if self._connected:
            return

        self._bound_loop = asyncio.get_running_loop()
        await self._spawn_process()
        self._reader_task = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._stderr_loop())
        # source: ADR-0532
        try:
            await asyncio.wait_for(
                self._perform_handshake(),
                timeout=self._connect_timeout_ms / 1000,
            )
        except asyncio.TimeoutError as exc:
            self.close()
            raise McpConnectionError(
                f"Handshake timed out after {self._connect_timeout_ms}ms",
                {"command": self._config.get("command")},
            ) from exc

    # source: ADR-0532
    _ALLOWED_COMMANDS = frozenset(
        {
            "node",
            "npx",
            "python",
            "python3",
            "cortex",
            "mcp-server",
            # source: ADR-0532
            *ALLOWED_UPSTREAM_COMMANDS,
        }
    )

    async def _spawn_process(self) -> None:
        """Spawn the child MCP server process.

        source: ADR-0532"""

        raw_command: str = self._config["command"]
        args = self._config.get("args") or []
        cwd = self._config.get("cwd")
        env = self._config.get("env")
        merged_env = {**os.environ, **(env or {})}
        # source: ADR-0532
        line_limit = 1024 * 1024 * 1024  # 1 GB

        # source: ADR-0532
        allowed = self._ALLOWED_COMMANDS | self._extra_allowed_commands
        base_cmd = raw_command.split("/")[-1] if "/" in raw_command else raw_command
        if base_cmd not in allowed:
            raise McpConnectionError(
                f"Command '{raw_command}' not in allowed list: {sorted(allowed)}"
            )
        # source: ADR-0532
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
        except asyncio.TimeoutError as exc:
            raise McpConnectionError(
                f"Connect timeout after {self._connect_timeout_ms}ms",
                {"command": command, "args": args},
            ) from exc
        except Exception as e:
            raise McpConnectionError(
                f"Failed to spawn: {e}",
                {"command": command, "args": args},
            ) from e

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
            ) from e

    async def call(self, name: str, args: dict | None = None) -> Any:
        """Call a tool on the remote MCP server."""
        if not self._connected:
            raise McpConnectionError("Not connected — call connect() first")

        self.tool_calls += 1
        self._touch_activity()

        result = await self._send("tools/call", {"name": name, "arguments": args or {}})

        # source: ADR-0532
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
        """True only when the client is usable FROM THE CALLING CONTEXT.

        precondition: called from within a running event loop (the pool's
                  ``get_client`` always is).
                postcondition: returns False if the handshake never completed, OR
                  the loop that owns this client's reader/streams is closed, OR a
                  DIFFERENT loop is now running. Returns True only when
                  reuse is safe. source: ingest stdio-deadlock RCA 2026-06-11.

        source: ADR-0532"""
        if not self._connected:
            return False
        bound = self._bound_loop
        if bound is None or bound.is_closed():
            return False
        try:
            return asyncio.get_running_loop() is bound
        except RuntimeError:
            # source: ADR-0532
            return False

    @property
    def max_concurrent_calls(self) -> int:
        """Permitted concurrent in-flight calls to this upstream child.

        source: ADR-0532"""
        raw = self._config.get("maxConcurrentCalls")
        try:
            return max(1, int(raw)) if raw is not None else 1
        except (TypeError, ValueError):
            return 1

    @property
    def busy(self) -> bool:
        """True while at least one JSON-RPC request is in flight.

        source: ADR-0532"""
        return len(self._pending) > 0

    @property
    def idle(self) -> bool:
        """True when the connection has been unused past the idle window.

        source: ADR-0532"""
        if self._pending:
            return False
        loop = asyncio.get_running_loop()
        return (loop.time() - self._last_activity) > (self._idle_timeout_ms / 1000)

    def close(self) -> None:
        """Gracefully close the connection."""
        self._connected = False
        self._bound_loop = None

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
            except Exception as exc:  # noqa: BLE001 — teardown continues past a failed close
                logger.debug("stdin close failed during client teardown: %s", exc)
            try:
                self._proc.terminate()
            except Exception as exc:  # noqa: BLE001 — process may already be gone
                logger.debug("terminate failed during client teardown: %s", exc)
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
        await self._write_frame(req_id, msg)

        # source: ADR-0532
        cap_ms = self._call_timeout_ms
        if cap_ms is None:
            result = await self._await_until_wedged(future, method, req_id)
        else:
            result = await self._await_capped(future, method, req_id, cap_ms / 1000)
        # source: ADR-0532
        self._touch_activity()
        return result

    async def _write_frame(self, req_id: int, msg: str) -> None:
        """Write one JSON-RPC frame and wait for the OS to accept it.

        source: ADR-0532"""
        try:
            self._proc.stdin.write((msg + "\n").encode())  # type: ignore
            await asyncio.wait_for(
                self._proc.stdin.drain(),  # type: ignore
                timeout=self._connect_timeout_ms / 1000,
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise McpConnectionError(
                f"Write to '{self._config.get('command')}' timed out after "
                f"{self._connect_timeout_ms}ms — the child is not reading "
                f"its stdin (wedged, or its stdout pipe is full and it has "
                f"stopped consuming input).",
                {"command": self._config.get("command")},
            ) from exc
        except BaseException:
            self._pending.pop(req_id, None)
            raise

    async def _await_capped(
        self, future: asyncio.Future, method: str, req_id: int, timeout_s: float
    ) -> Any:
        """Await ``future`` under the positive per-call wall-clock cap."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            return await asyncio.wait_for(future, timeout=timeout_s)
        except asyncio.CancelledError:
            # source: ADR-0532
            self._pending.pop(req_id, None)
            raise
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            elapsed = loop.time() - start
            raise McpConnectionError(
                f"MCP call '{method}' to '{self._config.get('command')}' "
                f"timed out after {elapsed:.1f}s "
                f"(limit {timeout_s:.0f}s). The upstream child did "
                f"not answer — it may be wedged writing a response larger "
                f"than the OS pipe buffer, or the reader loop is no longer "
                f"draining its stdout.",
                {"method": method, "elapsed_s": round(elapsed, 1)},
            ) from exc

    async def _await_until_wedged(
        self, future: asyncio.Future, method: str, req_id: int
    ) -> Any:
        """Await ``future`` with no wall-clock cap (callTimeoutMs == 0).

        Precondition:  the caller opted out of the per-call ceiling
                               (ingestion path: ap_bridge / pipeline_discovery).
                               Postcondition: returns the response however long the call
                               runs,
                               as long as the child keeps producing output on
                               stdout or stderr. Raises McpConnectionError only
                               after ``default_call_timeout_s()`` of TOTAL child
                               silence — the wedge signature (RCA 2026-06-11) —
                               never on elapsed time alone.

        source: ADR-0532"""
        window = default_call_timeout_s()
        start = time.monotonic()
        while True:
            if future.done():
                return future.result()
            silent_for = time.monotonic() - max(self._last_child_output, start)
            remaining = window - silent_for
            if remaining <= 0:
                self._pending.pop(req_id, None)
                future.cancel()
                self._raise_wedged(method, window, silent_for, start)
            try:
                # source: ADR-0532
                return await asyncio.wait_for(asyncio.shield(future), remaining)
            except asyncio.TimeoutError:
                continue  # re-check silence; output during the slice resets it
            except asyncio.CancelledError:
                # source: ADR-0532
                self._pending.pop(req_id, None)
                future.cancel()
                raise

    def _raise_wedged(
        self, method: str, window: float, silent_for: float, start: float
    ) -> NoReturn:
        elapsed = time.monotonic() - start
        raise McpConnectionError(
            f"MCP call '{method}' to '{self._config.get('command')}' "
            f"declared wedged: the upstream child produced no output "
            f"for {silent_for:.0f}s (silence limit {window:.0f}s, "
            f"call elapsed {elapsed:.1f}s). A live call is never "
            f"interrupted on duration; only total silence fails it.",
            {
                "method": method,
                "elapsed_s": round(elapsed, 1),
                "silent_s": round(silent_for, 1),
            },
        )

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())  # type: ignore

    def _touch_activity(self) -> None:
        try:
            self._last_activity = asyncio.get_running_loop().time()
        except RuntimeError:
            # source: ADR-0532
            pass

    async def _read_loop(self) -> None:
        # source: ADR-0532
        terminal_exc: BaseException | None = None
        try:
            while True:
                line = await self._proc.stdout.readline()  # type: ignore
                if not line:
                    # source: ADR-0532
                    break
                self._last_child_output = time.monotonic()
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
                    # source: ADR-0532
                    print(
                        f"[mcp-client] non-JSON line dropped: {decoded[:200]}",
                        file=sys.stderr,
                    )
                    continue
        except asyncio.CancelledError:
            terminal_exc = None
        except (
            asyncio.LimitOverrunError,
            asyncio.IncompleteReadError,
            ConnectionResetError,
            BrokenPipeError,
        ) as exc:
            # source: ADR-0532
            terminal_exc = exc
            print(
                f"[mcp-client] reader stream error: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        except Exception as exc:  # noqa: BLE001
            terminal_exc = exc
            print(
                f"[mcp-client] reader unexpected error: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        finally:
            # source: ADR-0532
            self._connected = False
            # source: ADR-0532
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(
                        McpConnectionError(
                            f"Upstream reader terminated: "
                            f"{type(terminal_exc).__name__ if terminal_exc else 'EOF'}"
                        )
                    )
            self._pending.clear()

    async def _stderr_loop(self) -> None:
        log_fh = self._open_stderr_log()
        try:
            while True:
                line = await self._proc.stderr.readline()  # type: ignore
                if not line:
                    break
                self._last_child_output = time.monotonic()
                decoded = line.decode("utf-8", errors="replace").rstrip()
                print(
                    f"[mcp-client] {self._config['command']}: {decoded}",
                    file=sys.stderr,
                )
                if log_fh is not None:
                    try:
                        log_fh.write(decoded + "\n")
                        log_fh.flush()
                    except OSError:
                        # source: ADR-0532
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 — pump death must not kill the client
            logger.debug("stderr pump terminated: %s", exc)
        finally:
            if log_fh is not None:
                try:
                    log_fh.close()
                except OSError:
                    # Best-effort close of the mirror log; nothing to salvage.
                    pass

    def _open_stderr_log(self):
        """Open a per-server stderr log file under ~/.cache/cortex/mcp-logs/.

        source: ADR-0532"""

        try:
            base = pathlib.Path.home() / ".cache" / "cortex" / "mcp-logs"
            base.mkdir(parents=True, exist_ok=True)
            raw = self._config.get("command") or "unknown"
            stem = raw.split("/")[-1] or "unknown"
            safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
            pid = os.getpid()
            return open(base / f"{safe}.{pid}.log", "a", encoding="utf-8")
        except OSError:
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
