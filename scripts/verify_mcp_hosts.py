#!/usr/bin/env python3
"""Exercise Cortex's hook-free stdio contract as common MCP hosts.

This is a protocol smoke test, not a mocked FastMCP unit test. Each case starts
the production entry point as a child process, sends a complete MCP lifecycle
batch, and verifies discovery plus one real SQLite-backed tool call. Client
names are deliberately varied: Cortex must not branch on Claude-specific host
identity, environment, or hooks.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


CLIENTS = ("claude-code", "gemini-cli", "codex-cli")
PROTOCOL_VERSION = "2025-06-18"
MIN_TOOL_COUNT = 52


class ContractError(RuntimeError):
    """A child completed without satisfying the MCP host contract."""


def _frames(client_name: str) -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "contract-test"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "memory_stats", "arguments": {}},
        },
    ]
    return "".join(
        json.dumps(message, separators=(",", ":")) + "\n" for message in messages
    )


def _environment(data_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CORTEX_CLAUDE_DIR": str(data_root),
            "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
            "CORTEX_MEMORY_AP_ENABLED": "0",
            # Regression environment: FastMCP's banner-time update check used
            # to import SOCKS support and abort before initialize. The MCP
            # runtime must not make that non-essential network request.
            "ALL_PROXY": "socks5://127.0.0.1:9",
            "all_proxy": "socks5://127.0.0.1:9",
        }
    )
    env.pop("FASTMCP_SHOW_SERVER_BANNER", None)
    env.pop("FASTMCP_CHECK_FOR_UPDATES", None)
    return env


def _responses(stdout: str) -> dict[int, dict[str, object]]:
    responses: dict[int, dict[str, object]] = {}
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and isinstance(message.get("id"), int):
            responses[message["id"]] = message
    return responses


def _result(
    responses: dict[int, dict[str, object]], request_id: int
) -> dict[str, object]:
    message = responses.get(request_id)
    if message is None:
        raise ContractError(f"missing response for request id={request_id}")
    if "error" in message:
        raise ContractError(f"request id={request_id} failed: {message['error']}")
    result = message.get("result")
    if not isinstance(result, dict):
        raise ContractError(f"request id={request_id} returned no object result")
    return result


def _run_client(
    client_name: str, command: list[str], data_root: Path, timeout: int
) -> dict[int, dict[str, object]]:
    process = subprocess.run(
        command,
        input=_frames(client_name),
        text=True,
        capture_output=True,
        env=_environment(data_root / client_name),
        timeout=timeout,
        check=False,
    )
    if process.returncode != 0:
        raise ContractError(
            f"{client_name}: server exited {process.returncode}\n{process.stderr}"
        )
    return _responses(process.stdout)


def _verify_initialize(
    client_name: str, responses: dict[int, dict[str, object]]
) -> None:
    initialized = _result(responses, 1)
    if initialized.get("protocolVersion") != PROTOCOL_VERSION:
        raise ContractError(
            f"{client_name}: negotiated {initialized.get('protocolVersion')!r}, "
            f"expected {PROTOCOL_VERSION!r}"
        )


def _verify_discovery(client_name: str, responses: dict[int, dict[str, object]]) -> int:
    tools = _result(responses, 2).get("tools", [])
    if not isinstance(tools, list):
        raise ContractError(f"{client_name}: tools/list returned {tools!r}")
    tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    if len(tools) < MIN_TOOL_COUNT or "memory_stats" not in tool_names:
        raise ContractError(
            f"{client_name}: discovered {len(tools)} tools; memory_stats="
            f"{'memory_stats' in tool_names}"
        )

    resources = _result(responses, 3).get("resources")
    if resources != []:
        raise ContractError(f"{client_name}: resources/list returned {resources!r}")

    prompt_names = {
        prompt.get("name")
        for prompt in _result(responses, 4).get("prompts", [])
        if isinstance(prompt, dict)
    }
    if "session_recall" not in prompt_names:
        raise ContractError(f"{client_name}: session_recall prompt was not discovered")
    return len(tools)


def _verify_memory_call(
    client_name: str, responses: dict[int, dict[str, object]]
) -> None:
    call_result = _result(responses, 5)
    if call_result.get("isError") is not False or not call_result.get(
        "structuredContent"
    ):
        raise ContractError(f"{client_name}: memory_stats failed: {call_result!r}")


def _verify(client_name: str, command: list[str], data_root: Path, timeout: int) -> int:
    responses = _run_client(client_name, command, data_root, timeout)
    _verify_initialize(client_name, responses)
    count = _verify_discovery(client_name, responses)
    _verify_memory_call(client_name, responses)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=2 * 60)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="server command after -- (default: current Python -m mcp_server)",
    )
    args = parser.parse_args()
    command = args.command or [sys.executable, "-m", "mcp_server"]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("server command after -- cannot be empty")

    with tempfile.TemporaryDirectory(prefix="cortex_mcp_hosts_") as temp_dir:
        for client_name in CLIENTS:
            count = _verify(client_name, command, Path(temp_dir), args.timeout)
            print(
                f"PASS {client_name}: initialize + discovery + "
                f"memory_stats ({count} tools)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
