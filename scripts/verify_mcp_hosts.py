#!/usr/bin/env python3
"""Exercise Cortex's hook-free stdio contract as common MCP hosts.

This is a protocol smoke test, not a mocked FastMCP/MCP-SDK unit test. Each
case starts the production entry point as a child process, sends a complete
MCP lifecycle batch, and verifies discovery plus one real SQLite-backed tool
call. Client names are deliberately varied: Cortex must not branch on
Claude-specific host identity, environment, or hooks.

Environment isolation: ci.yml's "Validate MCP host configurations" job runs
this script itself with PYTHONPATH=$GITHUB_WORKSPACE (so it can import
repo-root helpers). `_environment()` strips that before handing the env to
the spawned MCP server subprocess -- inherited via `os.environ.copy()`
otherwise, a leaked PYTHONPATH makes the subprocess's `mcp_server` import
resolve from the CHECKOUT rather than from whatever was actually installed
into its own venv, silently testing a Frankenstein combination (checkout
source + venv dependencies) neither this harness nor any real install ever
runs. A real end user bootstrapping via `uvx --from hypermnesia-mcp[...]`
never has PYTHONPATH set this way. Surfaced 2026-08-10, PR #331: the
checkout's `mcp_server/__main__.py` imported `mcp.server.mcpserver`
(mcp>=2.0.0's API) while the cold uvx venv had actually installed
fastmcp/mcp<2.0 (still-unreleased-with-this-change PyPI package) --
ModuleNotFoundError, masquerading as a real bootstrap failure.
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
import time
from typing import Literal

from mcp_server.tool_profiles import LEAN_TOOL_NAMES


CLIENTS = ("claude-code", "gemini-cli", "codex-cli")
PROFILES: tuple[Literal["full", "lean"], ...] = ("full", "lean")
STORAGE_SELECTIONS: tuple[Literal["sqlite", "auto"], ...] = ("sqlite", "auto")
# source: MCP protocol revision this harness's handshake declares -- mcp
# 2.0.0 accepts it on the "legacy" (pre-2026-07-28-envelope) handshake path.
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
    socks_proxy_regression: bool
    storage_selection: Literal["sqlite", "auto"]

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


def _environment(
    data_root: Path,
    *,
    socks_proxy_regression: bool,
    storage_selection: Literal["sqlite", "auto"] = "sqlite",
) -> dict[str, str]:
    env = os.environ.copy()
    # Strip a PYTHONPATH inherited from this harness's own invocation (see
    # the module docstring's "Environment isolation" section for why a
    # leaked PYTHONPATH corrupts the spawned MCP server's import resolution).
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "CORTEX_CLAUDE_DIR": str(data_root),
            "CORTEX_MEMORY_AP_ENABLED": "0",
        }
    )
    if storage_selection == "sqlite":
        env["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    else:
        # Exercise production auto-selection. In particular, do not inherit a
        # repository- or runner-level SQLite override that would make a
        # PostgreSQL-first smoke pass without ever attempting PostgreSQL.
        env.pop("CORTEX_MEMORY_STORE_BACKEND", None)
        env.pop("CORTEX_ALLOW_SQLITE_FALLBACK", None)
    if socks_proxy_regression:
        # Regression environment: FastMCP's banner-time update check used to
        # import SOCKS support and abort before initialize. The MCP runtime
        # must not make that non-essential network request. Cold uvx bootstrap
        # explicitly disables this fixture because it must reach PyPI.
        env["ALL_PROXY"] = "socks5://127.0.0.1:9"
        env["all_proxy"] = "socks5://127.0.0.1:9"
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
        env=_environment(
            case.data_root / case.client_name / case.profile,
            socks_proxy_regression=case.socks_proxy_regression,
            storage_selection=case.storage_selection,
        ),
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


def _verify(case: ContractCase) -> tuple[int, float]:
    started_at = time.monotonic()
    responses = _run_client(case)
    _verify_initialize(case, responses)
    count = _verify_tool_surface(case, responses)
    _verify_auxiliary_discovery(case, responses)
    _verify_memory_call(case, responses)
    return count, time.monotonic() - started_at


def _add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """Which host identities and profiles a run exercises."""
    parser.add_argument(
        "--clients",
        nargs="+",
        choices=CLIENTS,
        default=CLIENTS,
        help="client identities to exercise (default: all)",
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        choices=PROFILES,
        default=PROFILES,
        help="tool profiles to exercise (default: full lean)",
    )
    parser.add_argument(
        "--command-includes-profile",
        action="store_true",
        help=(
            "run the supplied command unchanged; requires exactly one --profiles value"
        ),
    )


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    """How each exercised case is actually driven."""
    parser.add_argument("--timeout", type=int, default=2 * 60)
    parser.add_argument(
        "--allow-bootstrap-network",
        action="store_true",
        help="do not inject the SOCKS regression fixture; intended for cold uvx",
    )
    parser.add_argument(
        "--storage-selection",
        choices=STORAGE_SELECTIONS,
        default="sqlite",
        help=(
            "storage policy to exercise: explicit sqlite (default), or auto "
            "for PostgreSQL-first selection with SQLite fallback"
        ),
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="base server command after --; profile flags are added by the test",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_selection_arguments(parser)
    _add_runtime_arguments(parser)
    return parser


def _resolved_command(
    parser: argparse.ArgumentParser, raw_command: list[str]
) -> tuple[str, ...]:
    command = raw_command or [sys.executable, "-m", "mcp_server"]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("server command after -- cannot be empty")
    return tuple(command)


def _case_command(
    base_command: tuple[str, ...], *, profile: str, command_includes_profile: bool
) -> tuple[str, ...]:
    if command_includes_profile:
        return base_command
    return (*base_command, "--profile", profile)


def _run_one_case(
    args: argparse.Namespace,
    base_command: tuple[str, ...],
    *,
    client_name: str,
    profile: str,
    temp_dir: str,
) -> None:
    case = ContractCase(
        client_name=client_name,
        profile=profile,
        command=_case_command(
            base_command,
            profile=profile,
            command_includes_profile=args.command_includes_profile,
        ),
        data_root=Path(temp_dir),
        timeout=args.timeout,
        socks_proxy_regression=not args.allow_bootstrap_network,
        storage_selection=args.storage_selection,
    )
    count, elapsed_seconds = _verify(case)
    print(
        f"PASS {case.label}: initialize + discovery + "
        f"memory_stats ({count} tools, {elapsed_seconds:.2f}s)"
    )


def _run_all_cases(args: argparse.Namespace, base_command: tuple[str, ...]) -> None:
    with tempfile.TemporaryDirectory(prefix="cortex_mcp_hosts_") as temp_dir:
        for client_name in args.clients:
            for profile in args.profiles:
                _run_one_case(
                    args,
                    base_command,
                    client_name=client_name,
                    profile=profile,
                    temp_dir=temp_dir,
                )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    base_command = _resolved_command(parser, args.command)
    if args.command_includes_profile and len(args.profiles) != 1:
        parser.error("--command-includes-profile requires exactly one --profiles value")

    _run_all_cases(args, base_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
