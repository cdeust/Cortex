#!/usr/bin/env python3
"""Exercise Cortex's hook-free stdio contract as common MCP hosts.

This is a protocol smoke test, not a mocked FastMCP/MCP-SDK unit test. Each
case starts the production entry point as a child process, sends a complete
MCP lifecycle batch, and verifies discovery plus one real SQLite-backed tool
call. Client names are deliberately varied: Cortex must not branch on
Claude-specific host identity, environment, or hooks.

Behaving *as a host* is load-bearing, not decorative: the exchange itself
lives in `mcp_host_client.py`, which keeps stdin open until every expected
response has arrived and closes it only then. Closing stdin is the MCP
shutdown signal (2025-06-18 §Lifecycle › Shutdown › stdio), so the previous
`subprocess.run(input=...)` shape signalled shutdown before reading a single
response and then demanded answers the protocol never owed it -- see that
module's docstring for the mcp 2.0.0 interleaving where the demand is
actually refused, in silence.

Environment isolation (PYTHONPATH stripping, the SOCKS regression fixture,
storage selection) also lives there, in `environment()`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import time
from typing import Literal

# Run as a script (`python scripts/verify_mcp_hosts.py`) sys.path[0] is
# scripts/, not the repo root, so the sibling below would not resolve under
# its package name. Importing it as `scripts.mcp_host_client` -- one
# canonical name whether this module is executed or imported by a test --
# keeps a single module identity, so a `ContractError` raised here is the
# same class a test catches (the dual-identity trap
# `tests_py/scripts/_craftsmanship_support.py` documents for its own
# siblings).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.mcp_host_client import (  # noqa: E402
    PROTOCOL_VERSION,
    ContractCase,
    ContractError,
    run_client,
)

from mcp_server.tool_profiles import LEAN_TOOL_NAMES  # noqa: E402


CLIENTS = ("claude-code", "gemini-cli", "codex-cli")
PROFILES: tuple[Literal["full", "lean"], ...] = ("full", "lean")
STORAGE_SELECTIONS: tuple[Literal["sqlite", "auto"], ...] = ("sqlite", "auto")
# source: tests_py/test_main.py standalone baseline plus its three documented
# optional upstream integrations (ingest_codebase, change_impact, ingest_prd).
MIN_FULL_TOOL_COUNT = 52
MAX_FULL_TOOL_COUNT = MIN_FULL_TOOL_COUNT + 3


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
    responses = run_client(case)
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
