"""Handler: codebase_analyze — scan a project and store code structure as memories.

Walks a project directory, parses source files using tree-sitter AST
(with regex fallback), and stores one memory per file with symbols as
entities and imports as relationships. Then runs cross-file resolution,
call graph extraction, and community detection.

Incremental by default: only processes files whose content hash changed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp_server.core.codebase_parser import (
    EXT_TO_LANG,
    build_memory_content,
    parse_file,
)
from mcp_server.handlers.codebase_analyze_helpers import (
    CODEBASE_AGENT_CONTEXT,
    FILE_TAG_PREFIX,
    HASH_TAG_PREFIX,
    collect_source_files,
    load_existing_hashes,
    mark_stale,
    persist_entities,
)
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Analyze a codebase and store its structure as Cortex memories. Uses tree-sitter AST for cross-file resolution, call graphs, and community detection. Incremental: only processes changed files.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Root directory (defaults to cwd)",
            },
            "languages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Language filter",
            },
            "max_files": {"type": "integer", "description": "Max files (default 500)"},
            "max_file_size_kb": {
                "type": "integer",
                "description": "Max file size KB (default 100)",
            },
            "incremental": {
                "type": "boolean",
                "description": "Only changed files (default true)",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Report only (default false)",
            },
            "domain": {"type": "string", "description": "Domain tag"},
        },
        "required": [],
    },
}

CODEBASE_SOURCE = "codebase_analyze"
CODEBASE_TAG = "codebase"
LANG_TAG_PREFIX = "lang:"
DEFAULT_MAX_FILES = 500
DEFAULT_MAX_FILE_SIZE_KB = 100

_store: MemoryStore | None = None


def _log(msg: str) -> None:
    print(f"[codebase-analyze] {msg}", file=sys.stderr)


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _parse_args(args: dict[str, Any] | None) -> tuple:
    """Extract and default handler arguments."""
    args = args or {}
    directory = Path(args.get("directory", "") or os.getcwd()).expanduser().resolve()
    languages = args.get("languages")
    max_files = int(args.get("max_files", DEFAULT_MAX_FILES))
    max_kb = int(args.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB))
    incremental = args.get("incremental", True)
    dry_run = args.get("dry_run", False)
    domain = args.get("domain", "")
    return directory, languages, max_files, max_kb * 1024, incremental, dry_run, domain


def _build_tags(rel_path: str, analysis: Any) -> list[str]:
    """Build memory tags for a file analysis."""
    tags = [
        CODEBASE_TAG,
        f"{FILE_TAG_PREFIX}{rel_path}",
        f"{HASH_TAG_PREFIX}{analysis.content_hash}",
        f"{LANG_TAG_PREFIX}{analysis.language}",
    ]
    for sym in analysis.definitions[:10]:
        tags.append(f"symbol:{sym.name}")
    return tags


def _set_memory_metadata(store: MemoryStore, memory_id: int) -> None:
    """Mark memory as semantic with boosted heat and importance."""
    try:
        store._conn.execute(
            "UPDATE memories SET store_type = 'semantic', "
            "heat = 0.7, importance = 0.5 WHERE id = %s",
            (memory_id,),
        )
        store._conn.commit()
    except Exception:
        pass


async def _store_file(
    root: Path,
    rel_path: str,
    analysis: Any,
    domain: str,
    store: MemoryStore,
) -> tuple[int | None, int, int]:
    """Store a single file as a memory with entities.

    Returns:
        Tuple of (memory_id, entities, relationships).
    """
    result = await remember_handler(
        {
            "content": build_memory_content(analysis),
            "tags": _build_tags(rel_path, analysis),
            "directory": str(root),
            "domain": domain,
            "source": CODEBASE_SOURCE,
            "force": True,
            "agent_topic": CODEBASE_AGENT_CONTEXT,
        }
    )
    memory_id = result.get("memory_id")
    if not result.get("stored") or not memory_id:
        return None, 0, 0

    _set_memory_metadata(store, memory_id)
    ents, rels = persist_entities(store, analysis, memory_id, domain or "code")
    return memory_id, ents, rels


def _parse_one_file(path: str, content: str) -> Any:
    """Parse a file with tree-sitter AST or regex fallback."""
    from mcp_server.core.ast_parser import is_available, parse_file_ast

    if is_available():
        return parse_file_ast(path, content.encode(errors="replace"))
    return parse_file(path, content)


async def _process_files(
    source_files: list[Path],
    root: Path,
    existing: dict[str, tuple[int, str]],
    incremental: bool,
    domain: str,
    store: MemoryStore,
) -> tuple[int, int, int, int, int, set[str], list[Any], dict[str, str]]:
    """Process source files: parse, diff, store.

    Returns counters, seen paths, analyses, and file contents map.
    """
    new_count, updated_count, unchanged_count = 0, 0, 0
    total_entities, total_relationships = 0, 0
    seen_paths: set[str] = set()
    all_analyses: list[Any] = []
    file_contents: dict[str, str] = {}

    for source_path in source_files:
        rel_path = _resolve_relative(source_path, root)
        seen_paths.add(rel_path)
        content = _safe_read(source_path)
        if content is None:
            continue
        file_contents[rel_path] = content
        analysis = _parse_one_file(rel_path, content)
        all_analyses.append(analysis)
        if incremental and rel_path in existing:
            if existing[rel_path][1] == analysis.content_hash:
                unchanged_count += 1
                continue
        _, ents, rels = await _store_file(root, rel_path, analysis, domain, store)
        total_entities += ents
        total_relationships += rels
        updated_count += 1 if rel_path in existing else 0
        new_count += 0 if rel_path in existing else 1

    return (
        new_count,
        updated_count,
        unchanged_count,
        total_entities,
        total_relationships,
        seen_paths,
        all_analyses,
        file_contents,
    )


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze a codebase and store its structure as Cortex memories."""
    root, languages, max_files, max_bytes, incremental, dry_run, domain = _parse_args(
        args
    )

    if not root.exists() or not root.is_dir():
        return {"analyzed": False, "reason": f"directory not found: {root}"}

    _log(f"scanning {root} (max_files={max_files}, incremental={incremental})")
    source_files = collect_source_files(root, languages, max_files, max_bytes)
    _log(f"found {len(source_files)} source files")

    if dry_run:
        langs = list({EXT_TO_LANG.get(f.suffix.lower(), "?") for f in source_files})
        return {
            "analyzed": False,
            "dry_run": True,
            "directory": str(root),
            "source_files": len(source_files),
            "languages": langs,
        }

    store = _get_store()
    existing = load_existing_hashes(store) if incremental else {}
    if incremental:
        _log(f"loaded {len(existing)} existing file hashes")

    new_c, upd_c, unch_c, ents, rels, seen, analyses, contents = await _process_files(
        source_files,
        root,
        existing,
        incremental,
        domain,
        store,
    )
    stale = _mark_deleted(existing, seen, store, incremental)

    # Phase 2: cross-file resolution, type references, communities
    graph_stats = _run_graph_analysis(analyses, contents, store, domain or "code")

    _log(f"done: {new_c} new, {upd_c} updated, {unch_c} unchanged, {stale} stale")
    _log(f"graph: {graph_stats}")
    return {
        "analyzed": True,
        "directory": str(root),
        "source_files": len(source_files),
        "new": new_c,
        "updated": upd_c,
        "unchanged": unch_c,
        "stale_marked": stale,
        "entities": ents,
        "relationships": rels,
        "graph": graph_stats,
        "languages": list(
            {EXT_TO_LANG.get(f.suffix.lower(), "?") for f in source_files}
        ),
    }


def _run_graph_analysis(
    analyses: list[Any],
    file_contents: dict[str, str],
    store: MemoryStore,
    domain: str,
) -> dict[str, int]:
    """Run cross-file resolution, type references, and communities."""
    from mcp_server.core.codebase_graph import (
        resolve_all_imports,
        extract_inheritance,
        detect_communities,
    )
    from mcp_server.core.codebase_type_resolver import resolve_type_references
    from mcp_server.handlers.codebase_analyze_helpers import (
        persist_file_edge,
        persist_inheritance_edge,
        persist_community_tags,
    )

    import_edges = resolve_all_imports(analyses)
    type_ref_edges = resolve_type_references(analyses, file_contents)
    all_file_edges = list(set(import_edges + type_ref_edges))
    inherit_edges = extract_inheritance(analyses)
    communities = detect_communities(all_file_edges, [])

    file_rels = persist_file_edge(store, all_file_edges, domain)
    inherit_rels = persist_inheritance_edge(store, inherit_edges, domain)
    persist_community_tags(store, communities)

    return {
        "import_edges": len(import_edges),
        "type_ref_edges": len(type_ref_edges),
        "total_file_edges": len(all_file_edges),
        "inheritance_edges": len(inherit_edges),
        "communities": len(set(communities.values())) if communities else 0,
        "file_edges_stored": file_rels,
        "inherit_edges_stored": inherit_rels,
    }


def _resolve_relative(source_path: Path, root: Path) -> str:
    """Resolve a source path to a root-relative string."""
    try:
        return str(source_path.relative_to(root))
    except ValueError:
        return str(source_path)


def _safe_read(source_path: Path) -> str | None:
    """Read a file, returning None on failure."""
    try:
        return source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _mark_deleted(
    existing: dict[str, tuple[int, str]],
    seen_paths: set[str],
    store: MemoryStore,
    incremental: bool,
) -> int:
    """Mark memories for files no longer on disk as stale."""
    if not incremental:
        return 0
    deleted_ids = [mid for path, (mid, _) in existing.items() if path not in seen_paths]
    return mark_stale(store, deleted_ids)
