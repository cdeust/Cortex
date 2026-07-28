"""Dev driver: run the ingest_codebase handler from the working tree.

Exercises the exact repo code (not the installed plugin) against the
production DB + the real upstream automatised-pipeline binary, so the
2026-06-11 pagination/wiki/dedup fixes can be verified live before a
release. Not wired into the MCP server — invoke manually:

    uv run python scripts/dev_run_ingest.py /path/to/project [--force]
"""

from __future__ import annotations

import asyncio
import json
import sys

_MIN_ARGC = 2  # source: structural — program name + <project_path>


async def main() -> int:
    if len(sys.argv) < _MIN_ARGC:
        print("usage: dev_run_ingest.py <project_path> [--force]")
        return 2
    project_path = sys.argv[1]
    force = "--force" in sys.argv[2:]

    from mcp_server.handlers.ingest_codebase import handler

    result = await handler({"project_path": project_path, "force_reindex": force})
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ingested") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
