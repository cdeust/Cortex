"""Handler: open_memory_dashboard — launch memory visualization in browser."""

from __future__ import annotations

import subprocess

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.server.http_dashboard_server import start_memory_dashboard_server

schema = {
    "description": "Launch the real-time memory dashboard in the browser. Shows heat map, entity graph, activity feed, and system stats.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict | None = None) -> dict:
    url = start_memory_dashboard_server(_get_store)

    try:
        subprocess.run(["open", url], capture_output=True, check=False)
    except Exception:
        try:
            subprocess.run(["xdg-open", url], capture_output=True, check=False)
        except Exception:
            pass

    return {
        "url": url,
        "message": f"Memory dashboard opened at {url}",
    }
