"""Command-line surface for scripts/verify_mcp_hosts.py.

Split out when that module reached its 300-line budget: defining the flags is
a separate concern from driving the contract, and nothing here imports the
MCP SDK, so the SDK-less `mcp-host-config` job keeps parsing arguments
whatever it later grows (ADR-1077, revision 2026-09-22).
"""

from __future__ import annotations

import argparse
import sys
from typing import Literal

CLIENTS = ("claude-code", "gemini-cli", "codex-cli")
PROFILES: tuple[Literal["full", "lean"], ...] = ("full", "lean")
STORAGE_SELECTIONS: tuple[Literal["sqlite", "auto"], ...] = ("sqlite", "auto")


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
    parser.add_argument(
        "--published-surface",
        action="store_true",
        help="the command resolves a released artifact, not this checkout; "
        "requires exactly one --clients and one --profiles value",
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


def build_parser(description: str | None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    _add_selection_arguments(parser)
    _add_runtime_arguments(parser)
    return parser


def resolved_command(
    parser: argparse.ArgumentParser, raw_command: list[str]
) -> tuple[str, ...]:
    command = raw_command or [sys.executable, "-m", "mcp_server"]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("server command after -- cannot be empty")
    return tuple(command)


def check_selection(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Refuse flag combinations whose meaning is not well defined.

    `--published-surface` suppresses the tool-count bounds, which stay valid
    and meaningful for any case whose command really is this checkout. A
    blanket flag threaded through a multi-client or multi-profile run would
    silently suppress them for those cases too, so the flag is confined to
    the single case it describes rather than trusted not to widen later.
    """
    if args.command_includes_profile and len(args.profiles) != 1:
        parser.error("--command-includes-profile requires exactly one --profiles value")
    if args.published_surface and (len(args.profiles) != 1 or len(args.clients) != 1):
        parser.error(
            "--published-surface requires exactly one --clients and one "
            "--profiles value: it describes one command, not a matrix"
        )
