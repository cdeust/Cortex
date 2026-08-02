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
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Literal

from mcp_server.tool_profiles import LEAN_TOOL_NAMES


CLIENTS = ("claude-code", "gemini-cli", "codex-cli")
PROFILES: tuple[Literal["full", "lean"], ...] = ("full", "lean")
# source: MCP protocol revision implemented by fastmcp==3.4.5.
PROTOCOL_VERSION = "2025-06-18"
# source: tests_py/test_main.py standalone baseline plus its three documented
# optional upstream integrations (ingest_codebase, change_impact, ingest_prd).
MIN_FULL_TOOL_COUNT = 52
MAX_FULL_TOOL_COUNT = MIN_FULL_TOOL_COUNT + 3


class ContractError(RuntimeError):
    """A child completed without satisfying the MCP host contract."""


@dataclass(frozen=True)
class ContractCase:
    """One host identity/profile combination and its isolated runtime."""

    client_name: str
    profile: Literal["full", "lean"]
    command: tuple[str, ...]
    data_root: Path
    timeout: int

    @property
    def label(self) -> str:
        return f"{self.client_name}/{self.profile}"


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
    env.pop("CORTEX_MCP_PROFILE", None)
    return env


def _responses(stdout: str) -> dict[int, dict[str, object]]:
    responses: dict[int, dict[str, object]] = {}
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContractError(
                f"malformed JSON-RPC frame on server stdout: {line!r}"
            ) from error
        if not isinstance(message, dict):
            raise ContractError(f"non-object JSON-RPC frame on stdout: {message!r}")
        request_id = message.get("id")
        if isinstance(request_id, int) and not isinstance(request_id, bool):
            responses[request_id] = message
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


def _run_client(case: ContractCase) -> dict[int, dict[str, object]]:
    process = subprocess.run(
        case.command,
        input=_frames(case.client_name),
        text=True,
        capture_output=True,
        env=_environment(case.data_root / case.client_name / case.profile),
        timeout=case.timeout,
        check=False,
    )
    if process.returncode != 0:
        raise ContractError(
            f"{case.label}: server exited {process.returncode}\n{process.stderr}"
        )
    return _responses(process.stdout)


def _verify_initialize(
    case: ContractCase, responses: dict[int, dict[str, object]]
) -> None:
    initialized = _result(responses, 1)
    if initialized.get("protocolVersion") != PROTOCOL_VERSION:
        raise ContractError(
            f"{case.label}: negotiated {initialized.get('protocolVersion')!r}, "
            f"expected {PROTOCOL_VERSION!r}"
        )
    instructions = initialized.get("instructions")
    marker = f"'{case.profile}' profile"
    if not isinstance(instructions, str) or marker not in instructions:
        raise ContractError(
            f"{case.label}: initialize instructions do not identify {marker}"
        )


def _verify_tool_surface(
    case: ContractCase, responses: dict[int, dict[str, object]]
) -> int:
    tools = _result(responses, 2).get("tools", [])
    if not isinstance(tools, list):
        raise ContractError(f"{case.label}: tools/list returned {tools!r}")
    tool_names = {
        name
        for tool in tools
        if isinstance(tool, dict)
        if isinstance(name := tool.get("name"), str)
    }
    if case.profile == "lean":
        missing = sorted(LEAN_TOOL_NAMES - tool_names)
        extra = sorted(tool_names - LEAN_TOOL_NAMES)
        if missing or extra:
            raise ContractError(
                f"{case.label}: lean surface drifted; missing={missing}, extra={extra}"
            )
    elif not MIN_FULL_TOOL_COUNT <= len(tools) <= MAX_FULL_TOOL_COUNT:
        raise ContractError(
            f"{case.label}: discovered {len(tools)} full tools; expected "
            f"{MIN_FULL_TOOL_COUNT}..{MAX_FULL_TOOL_COUNT}"
        )
    if "memory_stats" not in tool_names:
        raise ContractError(f"{case.label}: memory_stats was not discovered")
    return len(tools)


def _verify_auxiliary_discovery(
    case: ContractCase, responses: dict[int, dict[str, object]]
) -> None:
    # Cortex intentionally exposes tools and prompts, not MCP resources. The
    # empty-resource interop shim is documented at mcp_server/__main__.py #176;
    # adding a real resource is therefore an explicit contract change.
    resources = _result(responses, 3).get("resources")
    if resources != []:
        raise ContractError(f"{case.label}: resources/list returned {resources!r}")

    prompt_names = {
        prompt.get("name")
        for prompt in _result(responses, 4).get("prompts", [])
        if isinstance(prompt, dict)
    }
    if "session_recall" not in prompt_names:
        raise ContractError(f"{case.label}: session_recall prompt was not discovered")


def _verify_memory_call(
    case: ContractCase, responses: dict[int, dict[str, object]]
) -> None:
    call_result = _result(responses, 5)
    if call_result.get("isError") is not False or not call_result.get(
        "structuredContent"
    ):
        raise ContractError(f"{case.label}: memory_stats failed: {call_result!r}")


def _verify(case: ContractCase) -> int:
    responses = _run_client(case)
    _verify_initialize(case, responses)
    count = _verify_tool_surface(case, responses)
    _verify_auxiliary_discovery(case, responses)
    _verify_memory_call(case, responses)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=2 * 60)
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="base server command after --; profile flags are added by the test",
    )
    args = parser.parse_args()
    command = args.command or [sys.executable, "-m", "mcp_server"]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("server command after -- cannot be empty")

    with tempfile.TemporaryDirectory(prefix="cortex_mcp_hosts_") as temp_dir:
        for client_name in CLIENTS:
            for profile in PROFILES:
                case = ContractCase(
                    client_name=client_name,
                    profile=profile,
                    command=(*command, "--profile", profile),
                    data_root=Path(temp_dir),
                    timeout=args.timeout,
                )
                count = _verify(case)
                print(
                    f"PASS {case.label}: initialize + discovery + "
                    f"memory_stats ({count} tools)"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
