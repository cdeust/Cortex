"""Command line for per-project memory export and import (ADR-1113).

Usage::

    python -m mcp_server.portability export <project-root> <file> [--include-global]
    python -m mcp_server.portability import <file.jsonl> [--into <root>] [--trust-flags]

Both use the configured store (``CORTEX_MEMORY_STORE_BACKEND``, ``DATABASE_URL``
or the SQLite file), exactly as the MCP server does. Exit 0 on success, 1 when
the file is missing or not a valid export, 2 on a usage error.

source: ADR-1113"""

from __future__ import annotations

import argparse
import json
import sys


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m mcp_server.portability")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="write a project's memories")
    export.add_argument("project_root")
    export.add_argument("out")
    export.add_argument("--include-global", action="store_true")
    restore = commands.add_parser("import", help="read an export file")
    restore.add_argument("file")
    restore.add_argument("--into", dest="into_project_root")
    restore.add_argument(
        "--trust-flags",
        action="store_true",
        help="keep is_global, is_protected and is_team_decision from the file",
    )
    return parser


def _store():
    from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: PLC0415 — backend resolution happens at call time, like migrate
    from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — same

    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from mcp_server.handlers import memory_portability as portability  # noqa: PLC0415 — keeps --help free of store imports

    store = _store()
    try:
        if args.command == "export":
            result = portability.export_project(
                store, args.project_root, args.out, include_global=args.include_global
            )
        else:
            result = portability.import_export(
                store,
                args.file,
                into_project_root=args.into_project_root,
                trust_flags=args.trust_flags,
            )
    except (ValueError, OSError) as exc:
        print(f"cortex portability: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — entry point wiring, like every other entry

    wire_composition_root()
    sys.exit(main())
