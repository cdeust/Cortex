"""JSON-RPC messages the first-launch MCP stand-in says — stdlib only, 3.9 safe.

What the stand-in tells the host about itself must be what the real server
says (``mcp_server/__main__.py``: name, version, instructions from
``mcp_server.tool_profiles``), except ``listChanged``: the stand-in's lists
change once, at hand-over. ``tests_py/scripts/test_launcher_mcp_bootstrap.py``
compares these with the real server's ``initialize`` result.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading

# The initialize-handshake revisions of the locked MCP SDK (uv.lock mcp
# 2.3.0). source: mcp_types/version.py HANDSHAKE_PROTOCOL_VERSIONS (2.3.0)
HANDSHAKE_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
# The real server's identity. source: mcp_server/__main__.py MCPServer(...)
SERVER_INFO = {"name": "methodology-agent", "version": "1.0.0"}
# How long the child may take to install and answer initialize: a cold
# install measured 58 s, thirty times that is a broken install.
CHILD_START_SECONDS = 1800  # source: ADR-1104
CHILD_EXIT_SECONDS = 10  # source: ADR-1104 (an idle server exits on EOF in < 1 s)
NOT_READY_CODE = -32002  # source: JSON-RPC 2.0 server-error range (-32000..-32099)
START_FAILED_CODE = -32003  # source: JSON-RPC 2.0 server-error range (-32000..-32099)
METHOD_NOT_FOUND = -32601  # source: JSON-RPC 2.0 section 5.1
_EMPTY_LISTS = {
    "tools/list": "tools",
    "prompts/list": "prompts",
    "resources/list": "resources",
    "resources/templates/list": "resourceTemplates",
}


class HandOverError(RuntimeError):
    """The real server did not start or did not agree with the stand-in."""


def parse(line: str) -> dict | None:
    try:
        message = json.loads(line)
    except ValueError:
        return None
    return message if isinstance(message, dict) else None


def agreed_version(params: dict) -> str:
    """The host's revision when the SDK speaks it, else the SDK's newest."""
    asked = params.get("protocolVersion")
    return asked if asked in HANDSHAKE_VERSIONS else HANDSHAKE_VERSIONS[-1]


def initialize_result(request_id, version: str) -> dict:
    from mcp_server import tool_profiles  # noqa: PLC0415 — stdlib-only module, resolvable once the plugin root is on sys.path

    changing = {"listChanged": True}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": version,
            "capabilities": {
                "prompts": changing,
                "resources": dict(changing, subscribe=False),
                "tools": changing,
            },
            "serverInfo": SERVER_INFO,
            # The server resolves its profile from the args after the module.
            "instructions": tool_profiles.instructions(
                tool_profiles.resolve(sys.argv[2:])
            ),
        },
    }


def local_answer(message: dict, failure: str = "") -> dict:
    """The stand-in's answer to a request it handles itself.

    After a failed hand-over (``failure``), every request but ``ping`` gets
    that cause as an error: an empty list would read as a working server.
    """
    method, request_id = message["method"], message["id"]
    if failure and method != "ping":
        error = {"code": START_FAILED_CODE, "message": failure}
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    if method in _EMPTY_LISTS:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {_EMPTY_LISTS[method]: []},
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "server/discover":
        error = {"code": METHOD_NOT_FOUND, "message": "Method not found"}
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    error = {
        "code": NOT_READY_CODE,
        "message": (
            "Cortex is installing its runtime (first launch); "
            "its tools appear when it is ready"
        ),
    }
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def await_reply(child: subprocess.Popen, request_id: str) -> dict:
    """Read the child's stdout until it answers ``request_id``."""
    assert child.stdout is not None
    watchdog = threading.Timer(CHILD_START_SECONDS, child.kill)
    watchdog.start()
    try:
        for line in child.stdout:
            message = parse(line)
            if message is not None and message.get("id") == request_id:
                return message
    finally:
        watchdog.cancel()
    try:
        code = child.wait(timeout=CHILD_EXIT_SECONDS)  # reap: poll() can race EOF
    except subprocess.TimeoutExpired:
        code = None
    raise HandOverError(
        f"the server exited (code {code}) or stayed silent past "
        f"{CHILD_START_SECONDS} s before answering initialize; its stderr is above"
    )


def check_child_initialize(reply: dict, version: str) -> None:
    result = reply.get("result")
    if not isinstance(result, dict):
        raise HandOverError(f"the server refused initialize: {reply.get('error')}")
    if result.get("protocolVersion") != version:
        raise HandOverError(
            f"the server negotiated {result.get('protocolVersion')}, the host "
            f"was told {version}"
        )
