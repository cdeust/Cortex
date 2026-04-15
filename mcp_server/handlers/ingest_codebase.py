"""Handler: ingest_codebase — pull codebase analysis from the upstream
ai-automatised-pipeline MCP server into Cortex's store.

Flow
----
1. Resolve the project's graph path. If Cortex already has a cached
   graph_path memoised for this project, skip re-indexing; otherwise
   call the upstream ``analyze_codebase`` tool (which runs index +
   resolve + cluster).
2. Pull symbols, processes, and a handful of top symbols via
   ``search_codebase``/``get_processes``.
3. Project those upstream artefacts into Cortex's native stores:
     - Wiki pages: one reference page per detected process entry point
     - Memories:   one per top-N symbol (classifier-friendly text)
     - KG entities + edges: symbols as entities, calls/imports as edges
4. Return an ingestion summary (counts + sample page paths).

Cortex is the CONSUMER in this relationship — upstream owns analysis,
Cortex owns documentation and knowledge-graph state.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.handlers.ingest_helpers import (
    call_upstream,
    find_cached_graph,
    memoise_graph_path,
    normalise_mcp_payload,
)
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.wiki_store import write_page

logger = logging.getLogger(__name__)

# Upstream MCP server name in mcp-connections.json.
_UPSTREAM_SERVER = "codebase"

# How many top-ranked symbols to materialise as memories + KG nodes.
_DEFAULT_TOP_SYMBOLS = 50

# Max processes to materialise as wiki pages.
_DEFAULT_TOP_PROCESSES = 10

# ── Schema ──────────────────────────────────────────────────────────────

schema = {
    "description": (
        "Ingest a codebase analysis from the upstream ai-automatised-pipeline "
        "MCP server into Cortex's store. Triggers analyze_codebase (or reuses "
        "a cached graph), then materialises top-ranked symbols as memories + "
        "knowledge-graph entities, and entry-point processes as wiki reference "
        "pages. Use this to seed the Wiki / Board / Knowledge / Graph views "
        "from a freshly-indexed or re-indexed codebase. Cortex only consumes "
        "upstream analysis — it does not drive the pipeline. Returns counts "
        "and the wiki paths written."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["project_path"],
        "properties": {
            "project_path": {
                "type": "string",
                "description": (
                    "Absolute path to the codebase root to analyse. Used both "
                    "as the pipeline input and to memoise the resulting graph "
                    "path so subsequent ingests are idempotent."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Directory where the code graph is stored. Defaults to "
                    "~/.cache/cortex/code-graphs/<project-key>/."
                ),
                "examples": ["/Users/alice/.cache/cortex/code-graphs/cortex-ab12cd34"],
            },
            "language": {
                "type": "string",
                "description": "Language filter passed to analyze_codebase.",
                "enum": ["auto", "rust", "python", "typescript"],
                "default": "auto",
            },
            "force_reindex": {
                "type": "boolean",
                "description": (
                    "If true, call analyze_codebase even when a cached graph "
                    "path exists for this project."
                ),
                "default": False,
            },
            "top_symbols": {
                "type": "integer",
                "description": "Max number of top-ranked symbols to materialise as memories + KG nodes.",
                "default": _DEFAULT_TOP_SYMBOLS,
                "minimum": 0,
                "maximum": 1000,
                "examples": [25, 50, 200],
            },
            "top_processes": {
                "type": "integer",
                "description": "Max number of entry-point processes to materialise as wiki pages.",
                "default": _DEFAULT_TOP_PROCESSES,
                "minimum": 0,
                "maximum": 200,
                "examples": [5, 10, 25],
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


def _default_output_dir(project_path: str) -> str:
    """Default graph location under ~/.cache/cortex/code-graphs/."""
    from mcp_server.handlers.ingest_helpers import project_key

    return str(
        Path.home() / ".cache" / "cortex" / "code-graphs" / project_key(project_path)
    )


async def _ensure_graph(
    store: MemoryStore,
    project_path: str,
    output_dir: str,
    language: str,
    force_reindex: bool,
) -> tuple[str, dict[str, Any]]:
    """Return (graph_path, analyze_stats).

    Reuses the cached graph when available, otherwise calls upstream
    analyze_codebase and memoises the resulting graph path.
    """
    if not force_reindex:
        cached = find_cached_graph(store, project_path)
        if cached:
            return cached, {"reused_cached": True, "graph_path": cached}

    payload = await call_upstream(
        _UPSTREAM_SERVER,
        "analyze_codebase",
        {
            "path": str(Path(project_path).expanduser().resolve()),
            "output_dir": str(Path(output_dir).expanduser().resolve()),
            "language": language,
        },
    )
    result = normalise_mcp_payload(payload)
    graph_path = result.get("graph_path") or str(
        Path(output_dir).expanduser() / "graph"
    )
    memoise_graph_path(store, project_path, graph_path)
    result["graph_path"] = graph_path
    result["reused_cached"] = False
    return graph_path, result


def _short_symbol_summary(sym: dict[str, Any]) -> str:
    """Compact one-line summary for a ranked symbol."""
    qn = sym.get("qualified_name") or sym.get("name") or "<anon>"
    kind = sym.get("kind") or sym.get("label") or "symbol"
    community = sym.get("community")
    process = sym.get("process")
    parts = [f"{kind} {qn}"]
    if community is not None:
        parts.append(f"community={community}")
    if process:
        parts.append(f"process={process}")
    return " | ".join(parts)


def _write_symbol_memories(
    store: MemoryStore,
    symbols: list[dict[str, Any]],
    project_path: str,
    domain: str,
) -> list[int]:
    """Persist symbols as standalone memories. Returns new memory ids."""
    ids: list[int] = []
    for sym in symbols:
        qn = sym.get("qualified_name") or sym.get("name")
        if not qn:
            continue
        summary = _short_symbol_summary(sym)
        content = f"Code symbol: {qn}\n\n{summary}"
        if sym.get("file"):
            content += f"\nFile: {sym['file']}"
        record = {
            "content": content,
            "tags": ["code-reference", "ingest", sym.get("kind", "symbol")],
            "source": "ingest_codebase",
            "domain": domain,
            "directory_context": project_path,
            "importance": float(sym.get("relevance_score", 0.5) or 0.5),
            "heat": 0.8,
            "is_protected": False,
        }
        try:
            mem_id = store.insert_memory(record)
            ids.append(mem_id)
        except Exception as exc:
            logger.debug("symbol memory insert failed for %s: %s", qn, exc)
    return ids


def _write_symbol_entities(
    store: MemoryStore,
    symbols: list[dict[str, Any]],
    domain: str,
) -> dict[str, int]:
    """Persist symbols as KG entities. Returns {qualified_name: entity_id}."""
    name_to_id: dict[str, int] = {}
    for sym in symbols:
        qn = sym.get("qualified_name") or sym.get("name")
        if not qn:
            continue
        try:
            eid = store.insert_entity(
                {
                    "name": qn,
                    "type": sym.get("kind", "symbol"),
                    "domain": domain,
                    "heat": 0.8,
                }
            )
            name_to_id[qn] = eid
        except Exception as exc:
            logger.debug("symbol entity insert failed for %s: %s", qn, exc)
    return name_to_id


def _write_symbol_relationships(
    store: MemoryStore,
    symbols: list[dict[str, Any]],
    name_to_id: dict[str, int],
) -> int:
    """Persist calls/imports/implements edges between known entities.

    Only edges where BOTH endpoints are present in name_to_id are
    materialised — anything else would be a dangling reference.
    """
    written = 0
    for sym in symbols:
        src_name = sym.get("qualified_name") or sym.get("name")
        if not src_name or src_name not in name_to_id:
            continue
        src_id = name_to_id[src_name]
        for rel_type, key in (
            ("calls", "calls"),
            ("imports", "imports"),
            ("implements", "implements"),
        ):
            targets = sym.get(key) or []
            for target in targets:
                target_name = (
                    target if isinstance(target, str) else target.get("qualified_name")
                )
                if not target_name or target_name not in name_to_id:
                    continue
                try:
                    store.insert_relationship(
                        {
                            "source_entity_id": src_id,
                            "target_entity_id": name_to_id[target_name],
                            "relationship_type": rel_type,
                            "weight": 1.0,
                            "confidence": 0.9,
                        }
                    )
                    written += 1
                except Exception as exc:
                    logger.debug(
                        "edge insert failed (%s → %s): %s", src_name, target_name, exc
                    )
    return written


def _render_process_page(process: dict[str, Any]) -> tuple[str, str]:
    """Return (relative_wiki_path, markdown) for a process page."""
    entry = process.get("entry_point") or process.get("name") or "unknown"
    kind = process.get("entry_kind") or "entry"
    depth = process.get("bfs_depth") or process.get("depth") or 0
    symbol_count = process.get("symbol_count") or len(process.get("symbols", []) or [])
    slug = _slug(entry) or "process"
    rel_path = f"reference/codebase/{slug}.md"
    lines = [
        "---",
        f"title: Process — {entry}",
        "kind: reference",
        f"tags: [code-reference, process, {kind}]",
        "---",
        "",
        f"# Process — `{entry}`",
        "",
        f"- **Entry kind:** {kind}",
        f"- **BFS depth:** {depth}",
        f"- **Symbols in flow:** {symbol_count}",
        "",
    ]
    symbols = process.get("symbols") or []
    if symbols:
        lines.append("## Symbols reached")
        for sym in symbols[:50]:
            qn = sym if isinstance(sym, str) else sym.get("qualified_name", "")
            if qn:
                lines.append(f"- `{qn}`")
        if len(symbols) > 50:
            lines.append(f"- … and {len(symbols) - 50} more.")
        lines.append("")
    return rel_path, "\n".join(lines)


def _slug(text: str) -> str:
    """Light slugifier for process page filenames."""
    import re

    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:80]


def _write_process_pages(processes: list[dict[str, Any]]) -> list[str]:
    """Create wiki reference pages for each process. Returns paths written."""
    written: list[str] = []
    for proc in processes:
        try:
            rel_path, markdown = _render_process_page(proc)
            write_page(WIKI_ROOT, rel_path, markdown, mode="replace")
            written.append(rel_path)
        except Exception as exc:
            logger.debug("process page write failed: %s", exc)
    return written


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ingest a codebase analysis into Cortex's store."""
    args = args or {}
    project_path = (args.get("project_path") or "").strip()
    if not project_path:
        return {"ingested": False, "reason": "project_path is required"}

    output_dir = args.get("output_dir") or _default_output_dir(project_path)
    language = args.get("language", "auto") or "auto"
    force_reindex = bool(args.get("force_reindex", False))
    top_symbols = int(args.get("top_symbols", _DEFAULT_TOP_SYMBOLS))
    top_processes = int(args.get("top_processes", _DEFAULT_TOP_PROCESSES))

    store = _get_store()
    domain = f"code:{Path(project_path).name}"

    try:
        graph_path, analyze_stats = await _ensure_graph(
            store,
            project_path,
            output_dir,
            language,
            force_reindex,
        )
    except McpConnectionError as exc:
        return {
            "ingested": False,
            "reason": "upstream_mcp_unreachable",
            "error": str(exc),
        }
    except Exception as exc:
        logger.warning("ingest_codebase analyze step failed: %s", exc, exc_info=True)
        return {
            "ingested": False,
            "reason": "analyze_failed",
            "error": f"{type(exc).__name__}: {exc}",
        }

    symbols_raw: list[dict[str, Any]] = []
    processes_raw: list[dict[str, Any]] = []

    if top_symbols > 0:
        try:
            search_payload = await call_upstream(
                _UPSTREAM_SERVER,
                "search_codebase",
                {"graph_path": graph_path, "query": "", "limit": top_symbols},
            )
            search_result = normalise_mcp_payload(search_payload)
            symbols_raw = (
                search_result.get("results") or search_result.get("symbols") or []
            )
        except Exception as exc:
            logger.debug("search_codebase failed: %s", exc)

    if top_processes > 0:
        try:
            proc_payload = await call_upstream(
                _UPSTREAM_SERVER,
                "get_processes",
                {"graph_path": graph_path},
            )
            proc_result = normalise_mcp_payload(proc_payload)
            processes_raw = (proc_result.get("processes") or [])[:top_processes]
        except Exception as exc:
            logger.debug("get_processes failed: %s", exc)

    memory_ids = _write_symbol_memories(store, symbols_raw, project_path, domain)
    entity_ids = _write_symbol_entities(store, symbols_raw, domain)
    edge_count = _write_symbol_relationships(store, symbols_raw, entity_ids)
    wiki_paths = _write_process_pages(processes_raw)

    return {
        "ingested": True,
        "graph_path": graph_path,
        "analyze": analyze_stats,
        "memories_written": len(memory_ids),
        "entities_written": len(entity_ids),
        "edges_written": edge_count,
        "wiki_pages_written": wiki_paths,
        "symbol_count_seen": len(symbols_raw),
        "process_count_seen": len(processes_raw),
    }
