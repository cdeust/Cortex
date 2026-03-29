"""Handler: narrative — generate project story from memory.

Composition root: wires core narrative engine + memory store to produce
project-level summaries from stored memories.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.narrative import generate_brief_summary, generate_narrative
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

schema = {
    "description": "Generate a project narrative/story from stored memories for a directory or domain.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Project directory to narrate",
            },
            "domain": {
                "type": "string",
                "description": "Domain to narrate (alternative to directory)",
            },
            "brief": {
                "type": "boolean",
                "description": "Return brief summary only (default false)",
            },
        },
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate project narrative from memories."""
    args = args or {}
    directory = args.get("directory", "")
    domain = args.get("domain", "")
    brief = args.get("brief", False)

    store = _get_store()

    # Fetch relevant memories
    if directory:
        memories = store.get_memories_for_directory(directory, min_heat=0.0)
    elif domain:
        memories = store.get_memories_for_domain(domain, min_heat=0.0, limit=200)
    else:
        memories = store.get_hot_memories(min_heat=0.1, limit=200)

    if brief:
        summary = generate_brief_summary(memories)
        return {
            "summary": summary,
            "memory_count": len(memories),
        }

    result = generate_narrative(
        memories,
        directory=directory or domain,
    )
    return result
