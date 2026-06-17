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

# psycopg.rows is imported lazily inside _execute_view() — only reached on
# the PG path. Under the SQLite fallback psycopg may not be installed, so an
# eager top-level import would crash module load for all users on that backend.
# // Engineering choice: lazy import is the standard guard for optional
# // PG-only dependencies in composition-root handlers (see memory_store.py
# // which also defers `import psycopg` to _try_pg_verbose).

from mcp_server.core.wiki_schema_loader import load_registry
from mcp_server.core.wiki_view_executor import compile_view
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store


schema = {
    "description": (
        "Run a saved wiki view (a wiki/_views/<name>.md page that contains "
        "a `cortex-query` fenced block) or an ad-hoc inline cortex-query "
        "and return the resulting rows. The query is compiled through a "
        "safe DSL (parameterised SQL, no string interpolation) before being "
        "executed against the wiki tables. Phase 5.3 of the wiki redesign "
        "pipeline; the read-only query layer over wiki.pages / wiki.claim_"
        "events / wiki.concepts / wiki.drafts. Read-only; never mutates. "
        "Pass `list: true` to enumerate available saved views without "
        "executing one. Distinct from `wiki_list` (filesystem page "
        "listing), `wiki_read` (one page's markdown), and direct SQL "
        "(this gates everything through the safe compiler). Latency "
        "<200ms for typical views. Returns {view, table, row_count, "
        "rows, sql} or {error}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Name of a saved view — the file stem of a "
                    "wiki/_views/<name>.md page. Mutually exclusive with "
                    "`query`."
                ),
                "examples": ["open-questions", "stale-adrs", "recent-lessons"],
            },
            "query": {
                "type": "string",
                "description": (
                    "Inline cortex-query body (the YAML-style block content, "
                    "without the surrounding code fence). Use for ad-hoc "
                    "exploration; persist as a saved view if reused."
                ),
                "examples": [
                    "table: pages\nlimit: 5",
                    "table: claim_events\nfilter:\n  claim_type: decision\nlimit: 20",
                ],
            },
            "list": {
                "type": "boolean",
                "description": (
                    "Return the registry of saved views (name, rel_path, "
                    "description) instead of executing one. Useful for "
                    "discovery."
                ),
                "default": False,
                "examples": [False, True],
            },
        },
    },
}


_SQLITE_FALLBACK_MSG = (
    "wiki_view requires PostgreSQL — the wiki.pages / wiki.claim_events "
    "tables and the safe-DSL query layer are PG-only. The current backend "
    "is the reduced-capability SQLite fallback. Filesystem wiki authoring "
    "(wiki_read, wiki_list, wiki_write) still works. To enable wiki_view, "
    "configure DATABASE_URL and restart Cortex with a reachable PostgreSQL "
    "instance."
)


def _get_store() -> MemoryStore:
    # precondition: get_memory_settings() returns valid settings
    # postcondition: returns a MemoryStore instance (PG or SQLite)
    settings = get_memory_settings()
    return get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)


def _is_pg(store: object) -> bool:
    """Return True iff the store is the PostgreSQL backend.

    precondition: store is a MemoryStore produced by get_shared_store()
    postcondition: True iff type name is 'PgMemoryStore' (PG path is safe to
    use psycopg cursor API); False for SQLite fallback.
    // Engineering choice: name-based check avoids importing PgMemoryStore
    // into this module, which would force psycopg resolution at import time —
    // defeating the lazy-import goal. The class name is a stable interface
    // contract (see infrastructure/pg_store.py:107).
    """
    return type(store).__name__ == "PgMemoryStore"


def _execute_view(store: object, compiled: object, view_meta: dict) -> dict:
    """Run a compiled view against the PG store and return the result dict.

    precondition: _is_pg(store) is True; compiled.ok is True
    postcondition: returns {view, table, row_count, rows, sql} on success,
                   or {view, error, sql} on execution failure
    """
    # psycopg import deferred to here — only reachable on the PG path
    from psycopg.rows import dict_row  # noqa: PLC0415

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


def _list_views() -> dict:
    """Return the registry of saved views for `list: true` mode.

    precondition: WIKI_ROOT is a valid path (checked at module load)
    postcondition: returns {views: [...], count: int}
    """
    registry = load_registry(Path(WIKI_ROOT))
    return {
        "views": [
            {"name": v.name, "rel_path": v.rel_path, "description": v.description}
            for v in registry.views.values()
        ],
        "count": len(registry.views),
    }


def _resolve_query(args: dict) -> tuple[str, dict] | dict:
    """Resolve query_text + view_meta from args, or return an error dict.

    precondition: args is a non-None dict
    postcondition: returns (query_text, view_meta) tuple on success,
                   or an error dict when neither name= nor query= is provided,
                   or a not-found error dict when name= refers to unknown view
    """
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
        return view.query, {"name": view.name, "rel_path": view.rel_path}

    if inline_query:
        return inline_query, {"name": "<inline>", "rel_path": None}

    return {"error": "provide either name= or query="}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}

    if args.get("list"):
        return _list_views()

    resolved = _resolve_query(args)
    if isinstance(resolved, dict):
        return resolved
    query_text, view_meta = resolved

    # Guard: wiki_view DB execution is PG-only. Under SQLite return a
    # structured explanation instead of ImportError / AttributeError.
    store = _get_store()
    if not _is_pg(store):
        return {
            "view": view_meta,
            "error": "requires_postgresql",
            "message": _SQLITE_FALLBACK_MSG,
            "backend": type(store).__name__,
        }

    compiled = compile_view(query_text)
    if not compiled.ok:
        return {
            "view": view_meta,
            "error": "compile failed",
            "errors": compiled.errors,
            "sql": compiled.sql,
        }

    return _execute_view(store, compiled, view_meta)
