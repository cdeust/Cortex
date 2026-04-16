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
    "description": (
        "Generate a coherent project narrative from stored memories for a "
        "directory or domain. Clusters memories by topic + time, "
        "identifies the through-line, and renders either a multi-section "
        "story or (when `brief=true`) a one-paragraph executive summary. "
        "Use this for status updates, README seeds, or to onboard a new "
        "contributor with the project's actual history. Distinct from "
        "`get_project_story` (period-bucketed chronological chapters with "
        "explicit time ranges), `assess_coverage` (numeric score, no "
        "prose), and `recall` (raw ranked memories). Read-only. Latency "
        "~300-800ms. Returns {narrative, memory_count, themes}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "directory": {
                "type": "string",
                "description": (
                    "Absolute project directory to narrate. Pulls all memories "
                    "tagged to this path. Mutually exclusive with 'domain'."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "domain": {
                "type": "string",
                "description": (
                    "Domain identifier to narrate (e.g., 'cortex', 'auth-service'). "
                    "Used when 'directory' is omitted."
                ),
                "examples": ["cortex", "data-pipeline"],
            },
            "brief": {
                "type": "boolean",
                "description": (
                    "If true, return a one-paragraph executive summary instead "
                    "of the full multi-section narrative."
                ),
                "default": False,
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
