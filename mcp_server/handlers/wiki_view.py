"""Wiki Phase 5.3 — Execute a saved view.

A view is a wiki/_views/<name>.md page with a ``cortex-query`` fenced
block. The user authors views as ordinary wiki pages; this handler
loads the view, compiles it via the safe DSL, executes the SQL,
and returns the rows.

Modes:
  named view:       wiki_view({"name": "open-questions"})
  inline (testing): wiki_view({"query": "table: pages\nlimit: 5"})
  list views:       wiki_view({"list": true})

Composition root only — wiki_schema_loader supplies the views dict;
wiki_view_executor compiles; pg_store executes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.rows import dict_row

from mcp_server.core.wiki_schema_loader import load_registry
from mcp_server.core.wiki_view_executor import compile_view
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore


schema = {
    "description": (
        "Execute a wiki view. Either a named view from wiki/_views/ "
        "or an inline query block. Phase 5.3 of the redesign."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Name of a saved view (file stem in _views/).",
            },
            "query": {
                "type": "string",
                "description": "Inline cortex-query body (without code fence).",
            },
            "list": {
                "type": "boolean",
                "default": False,
                "description": "Return the registry of available views.",
            },
        },
    },
}


def _get_store() -> MemoryStore:
    settings = get_memory_settings()
    return MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}

    if args.get("list"):
        registry = load_registry(Path(WIKI_ROOT))
        return {
            "views": [
                {
                    "name": v.name,
                    "rel_path": v.rel_path,
                    "description": v.description,
                }
                for v in registry.views.values()
            ],
            "count": len(registry.views),
        }

    name = args.get("name")
    inline_query = args.get("query")

    if name:
        registry = load_registry(Path(WIKI_ROOT))
        view = registry.views.get(name)
        if view is None:
            return {
                "error": f"view {name!r} not found",
                "available": list(registry.views.keys()),
            }
        query_text = view.query
        view_meta = {"name": view.name, "rel_path": view.rel_path}
    elif inline_query:
        query_text = inline_query
        view_meta = {"name": "<inline>", "rel_path": None}
    else:
        return {"error": "provide either name= or query="}

    compiled = compile_view(query_text)
    if not compiled.ok:
        return {
            "view": view_meta,
            "error": "compile failed",
            "errors": compiled.errors,
            "sql": compiled.sql,
        }

    store = _get_store()
    with store._conn.cursor(row_factory=dict_row) as cur:
        try:
            cur.execute(compiled.sql, compiled.params)
            rows = list(cur.fetchall())
        except Exception as e:
            return {
                "view": view_meta,
                "error": f"execution failed: {e}",
                "sql": compiled.sql,
            }

    return {
        "view": view_meta,
        "table": compiled.table,
        "row_count": len(rows),
        "rows": rows,
        "sql": compiled.sql,
    }
