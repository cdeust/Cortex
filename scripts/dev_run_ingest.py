"""Dev driver: run the ingest_codebase handler from the working tree.

    uv run python scripts/dev_run_ingest.py /path/to/project [--force]

source: ADR-0728"""

from __future__ import annotations

import asyncio
import json
import sys
from mcp_server.handlers.ingest_codebase import handler

_MIN_ARGC = 2  # source: ADR-0728


async def main() -> int:
    if len(sys.argv) < _MIN_ARGC:
        print("usage: dev_run_ingest.py <project_path> [--force]")
        return 2
    project_path = sys.argv[1]
    force = "--force" in sys.argv[2:]

    result = await handler({"project_path": project_path, "force_reindex": force})
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ingested") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
