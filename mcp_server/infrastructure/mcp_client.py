"""Generic MCP client over stdio — spawns a child process, performs
JSON-RPC 2.0 handshake, calls tools.

Implements MCP 2025-11-25 handshake with version negotiation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from mcp_server.infrastructure.upstream_identity import ALLOWED_UPSTREAM_COMMANDS
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.mcp_call_timeout import default_call_timeout_s
import os
import shutil
import pathlib

logger = logging.getLogger(__name__)

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
        # Extra binaries allowed beyond _ALLOWED_COMMANDS (CWE-78 allowlist).
        # Callers (ap_bridge, mcp_client_pool) extend this for upstream
        # servers whose binaries the default list cannot know.
        self._extra_allowed_commands: set[str] = set()
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
        # The event loop that owns this client's stdout reader, stdin
        # stream, and pending-call futures. Set at connect(). A pooled
        # client may be handed to a DIFFERENT loop on reuse (batch
        # handlers run each call on a fresh per-call loop in a worker
        # thread — see tool_error_handler._run_coroutine_on_thread). If
        # the original loop has since closed, its _read_loop never drains
        # stdout again: the child blocks writing a >64KB response into a
        # full pipe and the reused caller's ``await future`` hangs forever.
        # ``connected`` checks loop liveness so the pool discards a client
        # bound to a dead/foreign loop and reconnects on the live one.
        # source: ingest stdio-deadlock RCA 2026-06-11.
        self._bound_loop: asyncio.AbstractEventLoop | None = None
        self.tool_calls = 0

    async def connect(self) -> None:
        """Spawn child process, perform MCP handshake, and list tools."""
        if self._connected:
            return

        self._bound_loop = asyncio.get_running_loop()
        await self._spawn_process()
        self._reader_task = asyncio.create_task(self._read_loop())
        asyncio.create_task(self._stderr_loop())
        # No fixed startup sleep. The previous ``await asyncio.sleep(1.5)``
        # was an unsourced guess at the child's "ready" time: too short
        # races a slow binary (initialize is sent, the child exits/EOFs
        # before reading it → "Handshake failed: Connection lost"), too
        # long adds latency to every connect. The ``initialize`` request
        # buffers on the child's stdin and its response is awaited, so a
        # slow-but-live server is handled correctly by the await. We bound
        # the handshake by the existing connect-timeout budget so a child
        # that never answers fails fast (the caller retries) instead of
        # hanging forever. source: AP MCP handshake flakiness RCA, 2026-06-03.
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

    # Allowlisted MCP server commands. Only these binaries may be spawned.
    # Config-supplied commands are validated against this list to prevent
    # command injection (CodeQL py/command-line-injection, CWE-78).
    _ALLOWED_COMMANDS = frozenset(
        {
            "node",
            "npx",
            "python",
            "python3",
            "cortex",
            "mcp-server",
            # The codebase-intelligence server ships a compiled Rust MCP
            # binary; the bridge resolves it from installed_plugins.json and
            # invokes it directly (not via node).
            # source: ap_bridge._resolve_command, upstream_identity.
            *ALLOWED_UPSTREAM_COMMANDS,
        }
    )

    async def _spawn_process(self) -> None:
        """Spawn the child MCP server process.

        Security: command must be in _ALLOWED_COMMANDS allowlist.
        Args are passed as a list (no shell=True). Environment is
        merged from os.environ + config, not constructed from user input.
        """

        raw_command: str = self._config["command"]
        args = self._config.get("args") or []
        cwd = self._config.get("cwd")
        env = self._config.get("env")
        merged_env = {**os.environ, **(env or {})}
        # Stream-buffer cap per JSON-RPC frame. Sized for the L6 path,
        # where AP responses with 100k+ symbols + edges legitimately
        # exceed 100MB. Keep an upper bound large enough that we never
        # cap real workloads; OS-level subprocess pipe buffering still
        # provides backpressure.
        line_limit = 1024 * 1024 * 1024  # 1 GB

        # Validate command against allowlist (CWE-78 mitigation).
        # In test/dev, extra commands can be allowed via _extra_allowed_commands.
        allowed = self._ALLOWED_COMMANDS | self._extra_allowed_commands
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
        """True only when the client is usable FROM THE CALLING CONTEXT.

        precondition: called from within a running event loop (the pool's
          ``get_client`` always is).
        postcondition: returns False if the handshake never completed, OR
          the loop that owns this client's reader/streams is closed, OR a
          DIFFERENT loop is now running. In those cases the cached client
          cannot drain the child's stdout for THIS caller, so the pool must
          discard it and reconnect on the live loop. Returns True only when
          reuse is safe. source: ingest stdio-deadlock RCA 2026-06-11.
        """
        if not self._connected:
            return False
        bound = self._bound_loop
        if bound is None or bound.is_closed():
            return False
        try:
            return asyncio.get_running_loop() is bound
        except RuntimeError:
            # No running loop in this thread — cannot safely reuse a
            # loop-bound client. Treat as not connected.
            return False

    @property
    def max_concurrent_calls(self) -> int:
        """Permitted concurrent in-flight calls to this upstream child.

        Read from the server's ``maxConcurrentCalls`` in mcp-connections.json;
        defaults to 1 (serialise the single-process child) when absent. Used
        by the per-server upstream governor. source: upstream_governor.py.
        """
        raw = self._config.get("maxConcurrentCalls")
        try:
            return max(1, int(raw)) if raw is not None else 1
        except (TypeError, ValueError):
            return 1

    @property
    def busy(self) -> bool:
        """True while at least one JSON-RPC request is in flight.

        ``_pending`` holds a future per request from the moment ``_send``
        writes the frame until ``_read_loop`` resolves it (or the reader
        terminates and fails it). A non-empty ``_pending`` therefore means
        the child is actively serving a call, so the pool must NOT evict
        this connection — doing so would cancel an in-flight request. This
        is the eviction-safety predicate consumed by the pool's LRU
        admission path. source: mcp_client_pool.get_client LRU eviction.
        """
        return len(self._pending) > 0

    @property
    def idle(self) -> bool:
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
        self._proc.stdin.write((msg + "\n").encode())  # type: ignore
        await self._proc.stdin.drain()  # type: ignore

        # Even when the operator opted into "no per-call timeout"
        # (callTimeoutMs == 0), enforce a hard ceiling so a wedged
        # upstream — or a client bound to a now-dead event loop whose
        # reader can no longer drain stdout — cannot deadlock the caller
        # forever. The ceiling is CORTEX_MCP_CALL_TIMEOUT_S (default 600s
        # = 10x the measured 32s analyze latency). source: ingest
        # stdio-deadlock RCA 2026-06-11 (4.5h hang at 0% CPU on both
        # sides; reader's owning loop had closed, ``await future`` was
        # unbounded).
        loop = asyncio.get_running_loop()
        effective_timeout = (
            self._call_timeout_ms / 1000
            if self._call_timeout_ms
            else default_call_timeout_s()
        )
        start = loop.time()
        try:
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            elapsed = loop.time() - start
            raise McpConnectionError(
                f"MCP call '{method}' to '{self._config.get('command')}' "
                f"timed out after {elapsed:.1f}s "
                f"(limit {effective_timeout:.0f}s). The upstream child did "
                f"not answer — it may be wedged writing a response larger "
                f"than the OS pipe buffer, or the reader loop is no longer "
                f"draining its stdout.",
                {"method": method, "elapsed_s": round(elapsed, 1)},
            ) from exc

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params:
            msg["params"] = params
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())  # type: ignore

    def _touch_activity(self) -> None:
        try:
            self._last_activity = asyncio.get_running_loop().time()
        except RuntimeError:
            # No running event loop (sync caller) — activity tracking is
            # only meaningful inside the loop; skipping it is safe.
            pass

    async def _read_loop(self) -> None:
        # Track terminal cause so all pending futures get a real error
        # instead of hanging forever when the reader exits.
        terminal_exc: BaseException | None = None
        try:
            while True:
                line = await self._proc.stdout.readline()  # type: ignore
                if not line:
                    # EOF — child closed stdout. Fall through to fail
                    # pending futures so callers do not block forever.
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
                    # Bad payload from the upstream is recoverable —
                    # log and continue rather than killing the loop.
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
            # Stream-level failure: most often a single response line
            # exceeded the configured ``limit`` bytes. Surface it as
            # the terminal cause for every pending future, so callers
            # see a clear McpConnectionError instead of hanging.
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
            # Reader is exiting → the child's stdout is gone, so the
            # connection is dead. Mark it disconnected at the ROOT here
            # (not only in close()) so the pool's ``existing.connected``
            # check discards this client and reconnects on the next call.
            # Without this the flag stayed True after a child crash and
            # the pool handed back a dead client, whose next stdin write
            # raised ``ConnectionResetError: Connection lost`` — the fast
            # failure seen on every ingest retry. source: ingest_codebase
            # ConnectionResetError RCA 2026-06-09.
            self._connected = False
            # Reader is exiting — wake every pending caller. Without
            # this, ``_send``'s ``await future`` blocks forever
            # (deadlock observed on long upstream responses).
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
                        # Mirror log file unwritable (disk full, rotated away);
                        # the stderr passthrough above already carried the line.
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

        Persists upstream MCP stderr (e.g. ai-architect-mcp indexer progress)
        for post-hoc investigation. Returns None on any error — logging
        failure must not break the connection.
        """

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
