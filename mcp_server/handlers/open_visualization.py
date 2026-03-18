"""Handler for the open_visualization tool — launches unified 3D graph in browser."""

from __future__ import annotations

import subprocess

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.server.http_viz_server import start_unified_viz_server

schema = {
    "description": "Launch the unified 3D neural graph in the browser. Combines methodology profiles, memories, and knowledge graph.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter to specific domain (optional)",
            },
        },
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
    args = args or {}

    url = start_unified_viz_server(
        profiles_getter=load_profiles,
        store_getter=_get_store,
    )

    try:
        subprocess.run(["open", url], capture_output=True, check=False)
    except Exception:
        try:
            subprocess.run(["xdg-open", url], capture_output=True, check=False)
        except Exception:
            pass

    return {
        "url": url,
        "message": f"Unified neural graph opened at {url}",
    }
